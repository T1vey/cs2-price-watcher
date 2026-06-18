import { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'

export default function AddModal({ apiBase, onClose, onAdded }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(null)
  const [target, setTarget] = useState('')
  const [recommend, setRecommend] = useState(null)
  const timer = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Debounced search
  useEffect(() => {
    if (query.length < 2) { setResults([]); return }
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      setLoading(true)
      try {
        const r = await fetch(`${apiBase}/api/search?q=${encodeURIComponent(query)}`)
        const d = await r.json()
        setResults(d.results || [])
      } catch { setResults([]) }
      setLoading(false)
    }, 400)
    return () => clearTimeout(timer.current)
  }, [query, apiBase])

  // Fetch recommendation when item selected
  useEffect(() => {
    if (!selected) { setRecommend(null); return }
    (async () => {
      try {
        const r = await fetch(`${apiBase}/api/recommend/${selected.goods_id}?source=${selected.source || 'buff'}`)
        if (r.ok) {
          const d = await r.json()
          setRecommend(d)
          if (d.recommended_target && !target) {
            setTarget(d.recommended_target.toFixed(2))
          }
        }
      } catch {}
    })()
  }, [selected, apiBase])

  const handleAdd = async () => {
    if (!selected) return
    const url = selected.source === 'youpin'
      ? `https://www.youpin898.com/goods/${selected.goods_id}`
      : `https://buff.163.com/goods/${selected.goods_id}`
    await fetch(`${apiBase}/api/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, target_price: parseFloat(target) || 0 })
    })
    onAdded()
  }

  return (
    <motion.div className="modal-bg" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      exit={{ opacity: 0 }} onClick={onClose}>
      <motion.div className="modal" initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
        onClick={e => e.stopPropagation()}>

        <h3>{selected ? '设置目标价' : '添加饰品'}</h3>
        <p className="sub">{selected ? '建议根据历史价格设置合理的监控阈值' : '搜索饰品名称或粘贴链接'}</p>

        {!selected ? (
          <>
            <div className="search-wrap">
              <span className="search-icon">🔍</span>
              <input ref={inputRef} className="search-input"
                placeholder="输入饰品名称（如 AK-47、蝴蝶刀）..."
                value={query} onChange={e => setQuery(e.target.value)} />
            </div>

            {results.length > 0 && (
              <div className="search-results">
                {results.map((r, i) => (
                  <div key={`${r.source}-${r.goods_id}-${i}`} className="search-item"
                    onClick={() => { setSelected(r); setQuery(''); setResults([]) }}>
                    {r.icon && <img src={r.icon} alt="" />}
                    <div className="search-item-info">
                      <div className="search-item-name">{r.name}</div>
                      <div className="search-item-meta">
                        {r.category && <span className="cat-tag">{r.category}</span>}
                        {r.source === 'youpin' ? '悠悠有品' : 'Buff'}
                        {r.on_sale_count ? ` · ${r.on_sale_count} 在售` : ''}
                      </div>
                    </div>
                    <div className="search-item-price">
                      ¥{r.price?.toFixed(2) || '—'}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {query.length >= 2 && results.length === 0 && !loading && (
              <div className="search-empty">未找到匹配的饰品</div>
            )}
          </>
        ) : (
          <>
            <div className="search-item" style={{ cursor: 'default', marginBottom: 16, background: 'var(--bg)', borderRadius: 10, padding: 14 }}>
              {selected.icon && <img src={selected.icon} alt="" />}
              <div className="search-item-info">
                <div className="search-item-name">{selected.name}</div>
                <div className="search-item-meta">
                  {selected.source === 'youpin' ? '悠悠有品' : 'Buff'}
                  {selected.on_sale_count ? ` · ${selected.on_sale_count} 在售` : ''}
                </div>
              </div>
              <div className="search-item-price">¥{selected.price?.toFixed(2) || '—'}</div>
            </div>

            {recommend && (
              <div className="recommend">
                <h4>📊 价格推荐（基于 7 天数据）</h4>
                <div className="recommend-row">
                  <div className="recommend-item">
                    <span className="r-label">最低</span>
                    <span className="r-val" style={{ color: 'var(--green)' }}>
                      ¥{recommend.low?.toFixed(2) || '—'}
                    </span>
                  </div>
                  <div className="recommend-item">
                    <span className="r-label">均价</span>
                    <span className="r-val" style={{ color: 'var(--text-2)' }}>
                      ¥{recommend.avg?.toFixed(2) || '—'}
                    </span>
                  </div>
                  <div className="recommend-item">
                    <span className="r-label">最高</span>
                    <span className="r-val" style={{ color: 'var(--red)' }}>
                      ¥{recommend.high?.toFixed(2) || '—'}
                    </span>
                  </div>
                </div>
                {recommend.recommended_target && (
                  <div style={{ textAlign: 'center', marginTop: 10, fontSize: 12, color: 'var(--blue)' }}>
                    建议目标价: ¥{recommend.recommended_target.toFixed(2)}（7 天最低 -10%）
                  </div>
                )}
              </div>
            )}

            <div className="field">
              <label>目标价格（低于此价提醒，0=不限）</label>
              <input className="field-input" type="number" step="0.01" min="0"
                placeholder="0" value={target}
                onChange={e => setTarget(e.target.value)} />
            </div>
          </>
        )}

        <div className="modal-btns">
          <button className="btn-outline" onClick={selected ? () => { setSelected(null); setRecommend(null) } : onClose}>
            {selected ? '返回' : '取消'}
          </button>
          {selected && (
            <button className="btn-primary" onClick={handleAdd}>添加监控</button>
          )}
        </div>
      </motion.div>
    </motion.div>
  )
}
