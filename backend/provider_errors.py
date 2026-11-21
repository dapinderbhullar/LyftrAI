import re
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from random import uniform

RATE_HEADERS = {
    "retry-after", "retry-after-ms", "x-ms-retry-after-ms",
    *(f"anthropic-ratelimit-{unit}-{field}"
      for unit in ("requests", "tokens", "input-tokens", "output-tokens")
      for field in ("limit", "remaining", "reset")),
    *(f"x-ratelimit-{field}-{unit}" for field in ("limit", "remaining", "reset")
      for unit in ("requests", "tokens")),
}
REQUEST_ID_HEADERS = ("x-request-id", "request-id", "x-amzn-requestid", "x-goog-request-id")
ERROR_TAGS = {
    "429", "rate_limit", "rate_limit_error", "ratelimiterror", "rate_limit_exceeded",
    "too_many_requests", "throttling_error", "resource_exhausted",
    "tokens", "requests", "tokens_per_minute", "requests_per_minute",
    "insufficient_quota", "quota_exceeded", "billing_hard_limit_reached",
    "billing_not_active", "billing_error", "budget_exceeded", "spend_limit_exceeded",
    "model_not_found", "invalid_model", "model_access_denied", "unsupported_model",
    "invalid_api_key", "authentication_error", "permission_denied", "invalid_request_error",
    "server_error", "service_unavailable", "overloaded_error", "invalid_argument",
    "not_found", "vendor_rate_limit", "litellm_rate_limit",
    "api_key_invalid", "api_key_expired", "api_key_service_blocked",
    "api_key_http_referrer_blocked", "api_key_ip_address_blocked",
    "unauthenticated", "failed_precondition", "billing_disabled",
    "free_tier_unavailable", "internal", "unavailable", "deadline_exceeded",
}
SUMMARY = {
    "spending_limit": "Provider indicated a billing, budget, or spending limit.",
    "insufficient_quota": "Provider indicated insufficient quota or exhausted credits.",
    "model_access": "Provider indicated an unavailable model or restricted model access.",
    "temporary_rate_limit": "Provider indicated temporary request or token throttling.",
    "authentication": "Provider reported an authentication failure.",
    "invalid_key": "Provider reported an invalid or expired API key.",
    "server_error": "Provider reported an upstream server error.",
    "unclassified_rate_limit": "Provider returned a rate-limit error without a clear cause.",
    "other": "Provider detail withheld because it may contain request data.",
}


def diagnose(exc, model, protected_values):
    response = getattr(exc, "response", None)
    payload = getattr(exc, "body", None)
    if response is not None:
        try:
            response_payload = response.json()
        except (ValueError, RuntimeError):
            pass
        else:
            if isinstance(response_payload, Mapping) and response_payload:
                payload = response_payload
    if not isinstance(payload, Mapping):
        payload = {}
    error = payload.get("error", payload)
    if not isinstance(error, Mapping):
        error = {}

    code = error.get("code") or getattr(exc, "code", None)
    error_type = error.get("type") or error.get("status") or getattr(exc, "type", None)
    status = error.get("code") if isinstance(error.get("code"), int) else None
    status = status or getattr(response, "status_code", None) or getattr(exc, "status_code", None)
    status = status if isinstance(status, int) and 100 <= status <= 599 else None
    reasons, quota, retry_info = [], [], None
    details = error.get("details")
    for detail in details if isinstance(details, list) else ():
        if not isinstance(detail, Mapping):
            continue
        detail_type = detail.get("@type")
        if detail_type == "type.googleapis.com/google.rpc.ErrorInfo":
            reason = detail.get("reason")
            if isinstance(reason, str) and reason.lower() in ERROR_TAGS:
                reasons.append(reason)
        elif detail_type == "type.googleapis.com/google.rpc.QuotaFailure":
            violations = detail.get("violations")
            for violation in violations if isinstance(violations, list) else ():
                if isinstance(violation, Mapping):
                    quota.extend(str(violation[field])[:512] for field in (
                        "quotaId", "quotaMetric", "quotaValue"
                    ) if isinstance(violation.get(field), (str, int)))
        elif detail_type == "type.googleapis.com/google.rpc.RetryInfo":
            value = detail.get("retryDelay")
            if isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,9})?s", value):
                retry_info = max(retry_info or 0, float(value[:-1]))
    # Use untrusted message text only for classification. It can echo whole prompts,
    # credentials, or arbitrary provider response data.
    signals = " ".join(str(value)[:4096] for value in (
        code, error_type, error.get("message"), getattr(exc, "message", None), *reasons, *quota
    ) if isinstance(value, (str, int))).lower()
    headers = {}
    for source in (getattr(response, "headers", None), getattr(exc, "headers", None)):
        if isinstance(source, Mapping):
            for name, value in source.items():
                name = name.lower()
                if name in RATE_HEADERS or name in REQUEST_ID_HEADERS:
                    headers.setdefault(name, value)

    retry_after = headers.get("retry-after")
    retry_seconds = parse_retry_after(retry_after)
    if retry_info is not None:
        retry_seconds = max(retry_seconds or 0, retry_info)
    for name in ("retry-after-ms", "x-ms-retry-after-ms"):
        value = headers.get(name)
        if isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}", value):
            retry_seconds = max(retry_seconds or 0, int(value) / 1000)

    if re.search(r"billing.hard.limit|spend(?:ing)?[ _-]+(?:limit|cap)|budget[ _-]+(?:exceeded|limit)|billing.not.active|billing.error|billing.disabled|free.tier.unavailable|free tier is not available|enable billing", signals):
        category = "spending_limit"
    elif "0" in quota or code in ("insufficient_quota", "quota_exceeded") or re.search(
        r"insufficient[ _-]quota|credit balance|out of credits|exhausted credits|per.?day|\b(?:rpd|tpd)\b|\blimit:\s*0\b", signals
    ):
        category = "insufficient_quota"
    elif status == 404 or re.search(r"model.not.found|invalid.model|unsupported.model|model.access.denied|(?:do not|don't) have access to (?:it|the model)|model .* does not exist|is not supported for generatecontent", signals):
        category = "model_access"
    elif re.search(r"api.key.invalid|api.key.expired|invalid.api.key|api key not valid", signals):
        category = "invalid_key"
    elif status in (401, 403) or re.search(r"unauthenticated|api.key.\w+.blocked", signals):
        category = "authentication"
    elif status is not None and status >= 500:
        category = "server_error"
    elif status == 429 and re.search(r"per.?minute|requests? per min|tokens? per min|\b(?:rpm|tpm)\b", signals):
        category = "temporary_rate_limit"
    elif re.search(r"exceeded your current quota|quota[ _-]exceeded", signals):
        category = "insufficient_quota"
    elif status == 429 and (
        retry_seconds is not None
        or any(name.startswith("x-ratelimit-reset-") for name in headers)
        or re.search(r"rate.limit.exceeded|rate limit reached", signals)
    ):
        category = "temporary_rate_limit"
    else:
        category = "unclassified_rate_limit" if status == 429 else "other"

    def safe(value, pattern):
        if isinstance(value, str) and re.fullmatch(pattern, value):
            if not any(protected and protected in value for protected in protected_values):
                return value
        return None

    tags = {}
    for name, value in (("error_code", code), ("error_type", error_type),
                        ("error_reason", next(iter(reasons), None)),
                        ("rate_limit_type", getattr(exc, "rate_limit_type", None))):
        if (isinstance(value, (str, int)) and str(value).lower() in ERROR_TAGS
                or name == "error_code" and isinstance(value, int) and 100 <= value <= 599):
            tags[name] = safe(str(value), r"[A-Za-z0-9_]{1,48}")

    limits = {
        name: cleaned for name, value in headers.items()
        if name in RATE_HEADERS and name != "retry-after"
        and (cleaned := safe(value, r"[0-9]{1,12}|(?:[0-9]{1,9}(?:\.[0-9]{1,6})?(?:ms|s|m|h|d)){1,5}|[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}(?:\.[0-9]{1,9})?Z"))
    }
    request_id = next((cleaned for value in (
        *(headers.get(name) for name in REQUEST_ID_HEADERS), getattr(exc, "request_id", None)
    ) if (cleaned := safe(value, r"(?:req[_-][A-Za-z0-9_-]{6,80}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})"))), None)
    # The configured model is server-owned. Avoid copying provider names from
    # untrusted error objects into logs.
    provider, separator, _ = model.partition("/")
    return {
        "exception": type(exc).__name__,
        "http_status": status,
        "provider": safe(provider, r"[a-zA-Z][a-zA-Z0-9_-]{0,39}") if separator else None,
        "classification": category,
        "provider_message_summary": SUMMARY[category],
        "retry_after": safe(retry_after, r"[0-9]{1,12}|[A-Za-z]{3}, [0-9]{2} [A-Za-z]{3} [0-9]{4} [0-9:]{8} GMT")
            if retry_seconds is not None else None,
        "rate_limit_headers": limits,
        "request_id": request_id,
        **tags,
    }, retry_seconds


def parse_retry_after(value):
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"[0-9]{1,12}", value):
        return int(value)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is not None:
            return max(0, (date - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def retry_delay(retry_after):
    # Allow only the first exponential-backoff step plus jitter. Honor a longer
    # provider delay by skipping the in-request retry instead of shortening it.
    delay = max(0.5, retry_after or 0) + uniform(0, 0.25)
    return delay if delay <= 2 else None
