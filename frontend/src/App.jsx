import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import './App.css'
import SearchBar from './components/SearchBar'
import ItemCard from './components/ItemCard'
import AddModal from './components/AddModal'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8765'

function formatTime(ts) {
  if (!ts) return 'Never'
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function App() {
  const [items, setItems] = useState([])
  const [histories, setHistories] = useState({})
  const [alerts, setAlerts] = useState([])
  const [meta, setMeta] = useState({ last_refresh: 0, refreshing: false, last_error: null })
  const [status, setStatus] = useState('loading')
  const [selectedResult, setSelectedResult] = useState(null)

  const fetchHistories = useCallback(async (watchItems) => {
    if (!watchItems.length) {
      setHistories({})
      return
    }

    const entries = await Promise.all(
      watchItems.map(async (item) => {
        try {
          const response = await fetch(`${API_BASE}/api/history/${item.goods_id}?limit=7`)
          if (!response.ok) throw new Error('history failed')
          const data = await response.json()
          return [item.goods_id, data.history || []]
        } catch {
          return [item.goods_id, []]
        }
      }),
    )
    setHistories(Object.fromEntries(entries))
  }, [])

  const fetchItems = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/items`)
      if (!response.ok) throw new Error('items failed')
      const data = await response.json()
      const watchItems = data.items || []
      setItems(watchItems)
      setMeta({
        last_refresh: data.last_refresh || 0,
        refreshing: Boolean(data.refreshing),
        last_error: data.last_error || null,
      })
      setStatus(data.refreshing ? 'refreshing' : 'online')
      fetchHistories(watchItems)
    } catch {
      setStatus('offline')
    }
  }, [fetchHistories])

  const fetchAlerts = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/alerts`)
      if (!response.ok) throw new Error('alerts failed')
      const data = await response.json()
      setAlerts(data.alerts || [])
    } catch {
      setAlerts([])
    }
  }, [])

  useEffect(() => {
    fetchItems()
    fetchAlerts()
    const timer = window.setInterval(() => {
      fetchItems()
      fetchAlerts()
    }, 7000)
    return () => window.clearInterval(timer)
  }, [fetchAlerts, fetchItems])

  const refresh = async () => {
    setStatus('refreshing')
    try {
      await fetch(`${API_BASE}/api/refresh`, { method: 'POST' })
    } finally {
      window.setTimeout(fetchItems, 900)
    }
  }

  const removeItem = async (gid) => {
    await fetch(`${API_BASE}/api/items/${gid}`, { method: 'DELETE' })
    fetchItems()
  }

  const stats = useMemo(() => {
    const alertCount = items.filter((item) => item.alerting || item.alerted).length
    const buffCount = items.filter((item) => item.source === 'buff').length
    const uuCount = items.filter((item) => item.source === 'youpin').length
    return { alertCount, buffCount, uuCount }
  }, [items])

  return (
    <div className="app-shell">
      <motion.header className="top-header" initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }}>
        <div className="brand-row">
          <div className="brand-mark">CS2</div>
          <div>
            <h1>Price Watcher</h1>
            <p>Market monitor for Buff and UU listings</p>
          </div>
        </div>
        <div className="header-actions">
          <span className={`connection-pill status-${status}`}>
            <span />{status === 'offline' ? 'Backend offline' : status === 'refreshing' ? 'Refreshing' : 'Live'}
          </span>
          <button type="button" className="secondary-button" onClick={refresh}>Refresh</button>
        </div>
      </motion.header>

      <main>
        <section className="search-hero" aria-label="Search market items">
          <div className="hero-copy">
            <span className="eyebrow">Watchlist search</span>
            <h2>Find the item, set a disciplined target, then let the monitor work.</h2>
          </div>
          <SearchBar apiBase={API_BASE} onSelect={setSelectedResult} />
        </section>

        <section className="summary-strip" aria-label="Monitor summary">
          <div className="summary-card">
            <span>Tracked</span>
            <strong>{items.length}</strong>
          </div>
          <div className="summary-card">
            <span>Buff / UU</span>
            <strong>{stats.buffCount} / {stats.uuCount}</strong>
          </div>
          <div className="summary-card">
            <span>Alerts</span>
            <strong className={stats.alertCount ? 'red-text' : ''}>{stats.alertCount}</strong>
          </div>
          <div className="summary-card">
            <span>Last refresh</span>
            <strong>{formatTime(meta.last_refresh)}</strong>
          </div>
        </section>

        {meta.last_error && <div className="inline-warning">Latest backend note: {meta.last_error}</div>}

        <div className="content-heading">
          <div>
            <span className="eyebrow">Watchlist</span>
            <h2>Tracked market cards</h2>
          </div>
          <p>Cards show the cached Buff and UU prices when available, recent monitor history, and target status.</p>
        </div>

        <AnimatePresence>
          {alerts.slice(0, 3).length > 0 && (
            <motion.aside
              className="alert-stack"
              initial={{ opacity: 0, x: 18 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 18 }}
            >
              {alerts.slice(0, 3).map((alert, index) => (
                <div className="alert-card" key={`${alert.ts}-${index}`}>
                  <span className="alert-dot" />
                  <div>
                    <strong>{alert.title || 'Price alert'}</strong>
                    <p>{alert.name ? `${alert.name}: ` : ''}{alert.message}</p>
                  </div>
                </div>
              ))}
            </motion.aside>
          )}
        </AnimatePresence>

        <motion.section className="cards-grid" layout>
          <AnimatePresence mode="popLayout">
            {items.map((item, index) => (
              <ItemCard
                key={`${item.source}-${item.goods_id}`}
                item={item}
                index={index}
                history={histories[item.goods_id] || []}
                onRemove={removeItem}
              />
            ))}
          </AnimatePresence>
        </motion.section>

        {items.length === 0 && status !== 'loading' && (
          <motion.div className="empty-state" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <span>⌕</span>
            <h3>No watched items yet</h3>
            <p>Use the search bar above to add a Buff or UU listing and create a target price.</p>
          </motion.div>
        )}
      </main>

      <AnimatePresence>
        {selectedResult && (
          <AddModal
            item={selectedResult}
            apiBase={API_BASE}
            onClose={() => setSelectedResult(null)}
            onAdded={() => {
              setSelectedResult(null)
              fetchItems()
              fetchAlerts()
            }}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

export default App
