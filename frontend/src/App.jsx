import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import './App.css'
import SearchBar from './components/SearchBar'
import AddModal from './components/AddModal'

const API = 'http://localhost:8765'

function App() {
  const [items, setItems] = useState([])
  const [alerts, setAlerts] = useState([])
  const [status, setStatus] = useState('loading')
  const [selectedResult, setSelectedResult] = useState(null)
  const [searchOpen, setSearchOpen] = useState(false)

  const fetchItems = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/items`)
      const d = await r.json()
      setItems(d.items || [])
      setStatus('ok')
    } catch { setStatus('error') }
  }, [])

  const fetchAlerts = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/alerts`)
      const d = await r.json()
      setAlerts(d.alerts || [])
    } catch {}
  }, [])

  useEffect(() => {
    fetchItems(); fetchAlerts()
    const t = setInterval(() => { fetchItems(); fetchAlerts() }, 5000)
    return () => clearInterval(t)
  }, [fetchItems, fetchAlerts])

  const removeItem = async (gid) => {
    await fetch(`${API}/api/items/${gid}`, { method: 'DELETE' })
    fetchItems()
  }

  const refresh = async () => {
    setStatus('refreshing')
    await fetch(`${API}/api/refresh`, { method: 'POST' })
    setTimeout(fetchItems, 2000)
  }

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-brand">
          <div className="logo-box">🎯</div>
          <div>
            <h1>CS2 Price Watcher</h1>
            <p className="subtitle">Buff & 悠悠有品 饰品价格监控</p>
          </div>
        </div>
        <div className="header-actions">
          <span className={`status-badge ${status}`}>
            <span className="dot" />
            {status === 'error' ? '离线' : status === 'refreshing' ? '刷新中' : '在线'}
          </span>
          <button className="btn-outline" onClick={refresh}>刷新</button>
          <button className="btn-primary" onClick={() => setSearchOpen(true)}>＋ 添加饰品</button>
        </div>
      </header>

      {/* Alerts */}
      <AnimatePresence>
        {alerts.slice(0, 3).map((a, i) => (
          <motion.div key={a.ts || i} className="alert-bar"
            initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }} transition={{ delay: i * 0.05 }}>
            <span className="alert-dot" />
            <span>{a.message || a.name}</span>
          </motion.div>
        ))}
      </AnimatePresence>

      {/* Stats */}
      <div className="stats-row">
        <div className="stat-card">
          <span className="stat-label">监控中</span>
          <span className="stat-value">{items.length}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Buff / UU</span>
          <span className="stat-value">
            {items.filter(i => i.source === 'buff').length} / {items.filter(i => i.source === 'youpin').length}
          </span>
        </div>
        <div className="stat-card">
          <span className="stat-label">异动</span>
          <span className="stat-value red">{items.filter(i => i.alerted).length || '0'}</span>
        </div>
      </div>

      {/* Items Grid */}
      <div className="grid">
        <AnimatePresence mode="popLayout">
          {items.map((item, i) => (
            <motion.div
              key={`${item.source}-${item.goods_id}`}
              className={`card ${item.alerted ? 'card-alert' : ''}`}
              initial={{ opacity: 0, y: 20, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ delay: i * 0.04, type: 'spring', stiffness: 400, damping: 30 }}
              whileHover={{ y: -3 }}
              layout
            >
              {/* Top: source + remove */}
              <div className="card-top">
                <span className={`tag ${item.source}`}>
                  {item.source === 'youpin' ? '悠悠有品' : 'Buff'}
                </span>
                <button className="x-btn" onClick={() => removeItem(item.goods_id)}>×</button>
              </div>

              {/* Icon + Name */}
              <div className="card-icon">
                {item.icon
                  ? <img src={item.icon} alt="" loading="lazy" />
                  : <div className="icon-fallback">🔫</div>}
              </div>
              <div className="card-name" title={item.name}>{item.name}</div>

              {/* Prices — the core data */}
              <div className="card-prices">
                <div className="price-main">
                  <span className="price-label">最低价</span>
                  <motion.span className="price-num" key={item.lowest}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}>
                    ¥{item.lowest != null ? item.lowest.toFixed(2) : '—'}
                  </motion.span>
                </div>
                <div className="price-divider" />
                <div className="price-side">
                  <div className="price-sub">
                    <span className="price-label">均价</span>
                    <span className="price-avg">¥{item.avg != null ? item.avg.toFixed(2) : '—'}</span>
                  </div>
                  <div className="price-sub">
                    <span className="price-label">在售</span>
                    <span className="price-count">{item.count ?? '—'}</span>
                  </div>
                </div>
              </div>

              {/* Target */}
              {item.target_price > 0 && (
                <div className={`card-target ${item.lowest != null && item.lowest <= item.target_price ? 'hit' : ''}`}>
                  🎯 目标 ¥{item.target_price.toFixed(2)}
                  {item.lowest != null && item.lowest <= item.target_price && <span className="hit-tag">已到达!</span>}
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {items.length === 0 && status !== 'loading' && (
        <motion.div className="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
          <div className="empty-icon">🎯</div>
          <h3>还没有监控的饰品</h3>
          <p>点击右上角「添加饰品」开始</p>
        </motion.div>
      )}

      {/* Search / Add Modal */}
      <AnimatePresence>
        {searchOpen && (
          <AddModal
            apiBase={API}
            onClose={() => { setSearchOpen(false); setSelectedResult(null) }}
            onAdded={() => { setSearchOpen(false); fetchItems() }}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

export default App
