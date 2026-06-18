import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

function formatPrice(price) {
  const value = Number(price)
  return Number.isFinite(value) && value > 0 ? `¥${value.toFixed(2)}` : 'Price pending'
}

function labelFor(source) {
  return source === 'youpin' ? 'UU' : 'Buff'
}

function SearchBar({ apiBase, onSelect }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [status, setStatus] = useState('idle')
  const [open, setOpen] = useState(false)
  const inputRef = useRef(null)

  useEffect(() => {
    const term = query.trim()
    if (term.length < 2) {
      setResults([])
      setStatus('idle')
      return undefined
    }

    let controller
    const timer = window.setTimeout(() => {
      controller = new AbortController()
      setStatus('searching')
      fetch(`${apiBase}/api/search?q=${encodeURIComponent(term)}`, { signal: controller.signal })
        .then(async (response) => {
          if (!response.ok) {
            const detail = await response.json().catch(() => ({}))
            throw new Error(detail.detail || 'Search failed')
          }
          return response.json()
        })
        .then((data) => {
          const list = Array.isArray(data) ? data : data.items || []
          setResults(list)
          setOpen(true)
          setStatus('ready')
        })
        .catch((error) => {
          if (error.name === 'AbortError') return
          setResults([])
          setOpen(true)
          setStatus('error')
        })
    }, 300)

    return () => {
      window.clearTimeout(timer)
      if (controller) controller.abort()
    }
  }, [apiBase, query])

  const choose = (item) => {
    onSelect(item)
    setOpen(false)
    inputRef.current?.blur()
  }

  return (
    <div className="search-shell">
      <div className={`search-box ${open ? 'is-open' : ''}`}>
        <span className="search-icon">⌕</span>
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => results.length && setOpen(true)}
          placeholder="Search CS2 skins across Buff and UU…"
          aria-label="Search skins"
        />
        <span className={`search-state search-${status}`}>
          {status === 'searching' ? 'Searching' : status === 'error' ? 'Offline' : query ? 'Enter item' : 'Ready'}
        </span>
      </div>

      <AnimatePresence>
        {open && query.trim().length >= 2 && (
          <motion.div
            className="search-results"
            initial={{ opacity: 0, y: -8, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.985 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            <div className="search-results-header">
              <span>{status === 'searching' ? 'Looking up markets' : `${results.length} results`}</span>
              <button type="button" onClick={() => setOpen(false)}>Close</button>
            </div>

            {status === 'error' && (
              <div className="search-empty">
                Search is unavailable. Check that the backend is running and market credentials are configured.
              </div>
            )}

            {status !== 'error' && status !== 'searching' && results.length === 0 && (
              <div className="search-empty">No matching items yet. Try a broader market name.</div>
            )}

            <div className="search-list">
              {results.map((item) => (
                <button
                  type="button"
                  className="search-result"
                  key={`${item.source}-${item.goods_id}`}
                  onClick={() => choose(item)}
                >
                  <div className="result-icon">
                    {item.icon ? <img src={item.icon} alt="" loading="lazy" /> : <span>CS2</span>}
                  </div>
                  <div className="result-copy">
                    <strong>{item.name}</strong>
                    <span>#{item.goods_id}</span>
                  </div>
                  <div className="result-market">
                    <span className={`market-chip ${item.source === 'youpin' ? 'chip-uu' : 'chip-buff'}`}>{labelFor(item.source)}</span>
                    <span>{formatPrice(item.price)}</span>
                  </div>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default SearchBar
