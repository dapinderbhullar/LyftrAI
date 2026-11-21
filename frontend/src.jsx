import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import Markdown from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'
import './style.css'

const api = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')
const examples = [
  { icon: 'bulb', title: 'Learn something', prompt: 'Explain how a rainbow forms' },
  { icon: 'compass', title: 'Make a plan', prompt: 'Help me plan a weekend trip' },
  { icon: 'pen', title: 'Start writing', prompt: 'Give me a quick writing exercise' },
]
const paths = {
  mark: 'M12 2v20M2 12h20M5 5l14 14M19 5 5 19',
  plus: 'M12 5v14M5 12h14',
  chat: 'M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l1.5-3A7.5 7.5 0 1 1 20 11.5Z',
  menu: 'M4 6h16M4 12h16M4 18h16',
  close: 'm6 6 12 12M18 6 6 18',
  sun: 'M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M19 5l-1.5 1.5m-11 11L5 19M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
  moon: 'M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z',
  bulb: 'M9 18h6m-5 3h4m-5-5c0-2-3-3-3-7a6 6 0 1 1 12 0c0 4-3 5-3 7',
  compass: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-6-3-2 4-4 2 2-4 4-2Z',
  pen: 'm4 20 1-5L16 4l4 4L9 19l-5 1ZM14 6l4 4',
  arrow: 'M6 18 18 6M9 6h9v9',
  send: 'M12 19V5m-6 6 6-6 6 6',
  copy: 'M8 8h12v12H8zM4 16V4h12',
  check: 'm5 12 4 4L19 6',
}

function Icon({ name }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>
}

function CopyButton({ text, label }) {
  const [feedback, setFeedback] = useState('')
  useEffect(() => {
    if (!feedback) return
    const timer = setTimeout(() => setFeedback(''), 1800)
    return () => clearTimeout(timer)
  }, [feedback])

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setFeedback('Copied')
    } catch {
      setFeedback('Copy unavailable')
    }
  }

  return <button className="copy-button" type="button" aria-label={label} title={label} onClick={copy}>
    <Icon name={feedback === 'Copied' ? 'check' : 'copy'} />
    <span aria-live="polite">{feedback || label}</span>
  </button>
}

const markdownComponents = {
  table: ({ node: _node, ...props }) => <div className="reply-table"><table {...props} /></div>,
  pre: ({ children, node: _node, ...props }) => <div className="code-block">
    <div className="code-toolbar">
      <span>{children?.props?.className?.replace(/^language-/, '') || 'Code'}</span>
      <CopyButton text={children?.props?.children ?? ''} label="Copy code" />
    </div>
    <pre {...props}>{children}</pre>
  </div>,
}

function Reply({ text, metadata }) {
  return <article className="reply" data-testid="assistant-message">
    <div className="reply-header">
      <span className="assistant-label"><span className="mini-mark"><Icon name="mark" /></span><strong>Assistant</strong></span>
      <CopyButton text={text} label="Copy response" />
    </div>
    <div className="reply-text">
      <Markdown remarkPlugins={[remarkGfm, remarkBreaks]} components={markdownComponents} skipHtml disallowedElements={['img']}>
        {text}
      </Markdown>
    </div>
    <dl className="metadata">
      <div className={`source ${metadata.resolution_source === 'LLM_CACHE' ? 'cached' : ''}`}>
        <dt className="sr-only">Source</dt>
        <dd><span className="sr-only" aria-hidden="true" data-testid="meta-source">{metadata.resolution_source}</span>
          <span>{metadata.resolution_source === 'LLM_CACHE' ? 'Cached response' : 'Live response'}</span>
        </dd>
      </div>
      <div><dt>Model</dt><dd data-testid="meta-model">{metadata.model}</dd></div>
      <div><dt>Latency</dt><dd data-testid="meta-latency">{metadata.latency_ms} ms</dd></div>
      <div><dt>Input tokens</dt><dd data-testid="meta-input-tokens">{metadata.input_tokens}</dd></div>
      <div><dt>Output tokens</dt><dd data-testid="meta-output-tokens">{metadata.output_tokens}</dd></div>
    </dl>
  </article>
}

function newSession() {
  return globalThis.crypto?.randomUUID?.() ||
    Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
}

function Chat() {
  const [session, setSession] = useState(newSession)
  const [theme, setTheme] = useState(() => localStorage.getItem('lyftr-theme') === 'light' ? 'light' : 'dark')
  const [navigationOpen, setNavigationOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [turns, setTurns] = useState([])
  const [pending, setPending] = useState(false)
  const input = useRef(null)
  const end = useRef(null)
  const menu = useRef(null)
  const closeNavigation = useRef(null)
  const sending = useRef(false)

  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [turns, pending])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('lyftr-theme', theme)
    document.querySelector('meta[name="theme-color"]').content = theme === 'dark' ? '#151816' : '#f6f7f1'
  }, [theme])
  useEffect(() => {
    if (!navigationOpen) return
    closeNavigation.current?.focus()
    const mobile = window.matchMedia('(max-width: 800px)')
    function escape(event) {
      if (event.key === 'Escape') dismissNavigation()
    }
    function resize(event) {
      if (!event.matches) {
        setNavigationOpen(false)
        requestAnimationFrame(() => input.current?.focus())
      }
    }
    window.addEventListener('keydown', escape)
    mobile.addEventListener('change', resize)
    return () => {
      window.removeEventListener('keydown', escape)
      mobile.removeEventListener('change', resize)
    }
  }, [navigationOpen])

  function dismissNavigation() {
    setNavigationOpen(false)
    requestAnimationFrame(() => menu.current?.focus())
  }

  function startChat() {
    if (sending.current) return
    setSession(newSession())
    setTurns([])
    setDraft('')
    setNavigationOpen(false)
    requestAnimationFrame(() => input.current?.focus())
  }

  async function sendMessage(value, replaceLast = false) {
    const message = value.trim()
    if (!message || sending.current) return
    sending.current = true
    setPending(true)
    if (!replaceLast) setDraft('')
    setTurns(previous => [...(replaceLast ? previous.slice(0, -1) : previous), { message }])
    let outcome
    try {
      const response = await fetch(api + '/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session, message }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        const error = response.status === 503
          ? 'The model is temporarily unavailable. Try again in a moment.'
          : typeof body.detail === 'string' ? body.detail : 'The message could not be sent. Check your input and try again.'
        outcome = { error, retryable: response.status === 503 && body.detail === 'all providers unavailable' }
      } else {
        outcome = await response.json()
      }
    } catch {
      outcome = { error: 'Could not reach the chat service. Check your connection and try again.' }
    } finally {
      setTurns(previous => [...previous.slice(0, -1), { message, ...outcome }])
      sending.current = false
      setPending(false)
      input.current?.focus()
    }
  }

  return <div className="workspace" data-navigation-open={navigationOpen}>
    {navigationOpen && <button className="scrim" type="button" tabIndex={-1} aria-label="Dismiss navigation" onClick={dismissNavigation} />}
    <aside className="sidebar" id="chat-navigation" aria-label="Chat workspace">
      <div className="sidebar-brand">
        <span className="brand-mark"><Icon name="mark" /></span>
        <div><strong>Lyftr<span>AI</span></strong><small>Chat workspace</small></div>
        <button ref={closeNavigation} className="icon-button close-navigation" type="button" aria-label="Close navigation" onClick={dismissNavigation}><Icon name="close" /></button>
      </div>
      <button className="new-chat" type="button" disabled={pending} onClick={startChat}>
        <Icon name="plus" /> New chat
      </button>
      <div className="sidebar-section">
        <p>Session</p>
        <div className="active-chat" title={turns[0]?.message || 'Current conversation'}>
          <Icon name="chat" /><span>{turns[0]?.message || 'Current conversation'}</span>
        </div>
      </div>
      <div className="sidebar-bottom">
        <button className="theme-toggle" type="button" aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} /> {theme === 'dark' ? 'Light mode' : 'Dark mode'}
        </button>
      </div>
    </aside>
    <main className="main-chat" inert={navigationOpen || undefined}>
    <header className="topbar">
      <button ref={menu} className="icon-button open-navigation" type="button" aria-label="Open navigation" aria-controls="chat-navigation" aria-expanded={navigationOpen} onClick={() => setNavigationOpen(true)}><Icon name="menu" /></button>
      <span className="topbar-brand">LyftrAI</span>
      <span className="topbar-divider" aria-hidden="true">/</span>
      <strong>Chat</strong>
    </header>
    <section className="conversation" aria-label="Conversation" aria-live="polite">
      {!turns.length && <div className="welcome">
        <div className="hero-art" aria-hidden="true"><span><Icon name="mark" /></span></div>
        <h1>What’s on your mind?</h1>
        <p className="welcome-description">Ask a question, explore an idea, or get help with what’s next.</p>
        <div className="suggestions">
          <p>Try a prompt</p>
          <div className="examples">{examples.map(({ icon, title, prompt }) => <button key={prompt} type="button" aria-label={prompt} onClick={() => {
          setDraft(prompt)
          input.current?.focus()
          }}>
            <span className="example-top"><span className="example-icon"><Icon name={icon} /></span><Icon name="arrow" /></span>
            <strong>{title}</strong><span>{prompt}</span>
          </button>)}</div>
        </div>
      </div>}
      {turns.map(({ message, reply, metadata, error, retryable }, index) => <div className="turn" key={index}>
        <p className="user">{message}</p>
        {reply && <Reply text={reply} metadata={metadata} />}
        {error && <div className="error" role="alert"><p>{error}</p><div className="error-actions"><button type="button" onClick={() => {
          setDraft(message)
          input.current?.focus()
        }}>Restore message</button>
        {retryable && index === turns.length - 1 && <button type="button" disabled={pending} onClick={() => sendMessage(message, true)}>Retry</button>}</div></div>}
      </div>)}
      {pending && <div className="pending" role="status"><span className="dots" aria-hidden="true"><i /><i /><i /></span><span>Waiting for a reply…</span></div>}
      <div ref={end} />
    </section>
    <div className="composer-dock"><form className="composer" onSubmit={event => {
      event.preventDefault()
      sendMessage(draft)
    }}>
      <textarea ref={input} data-testid="chat-input" aria-label="Message" placeholder="Message LyftrAI…" rows="2" maxLength={4000}
        value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            event.currentTarget.form.requestSubmit()
          }
        }} />
      <div className="composer-tools">
        <span className="keyboard-hint"><kbd>↵</kbd> sends <span>·</span> <kbd>Shift</kbd> + <kbd>↵</kbd> for a new line</span>
        <span className="character-count">{draft.length.toLocaleString()} / 4,000</span>
        <button className="send-button" type="submit" data-testid="send-button" disabled={pending || !draft.trim()}>Send <Icon name="send" /></button>
      </div>
    </form></div>
  </main></div>
}

createRoot(document.getElementById('root')).render(<Chat />)
