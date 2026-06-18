import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'

function formatPrice(value) {
  const num = Number(value)
  return Number.isFinite(num) && num > 0 ? `¥${num.toFixed(2)}` : '—'
}

function sourceLabel(source) {
  return source === 'youpin' ? 'UU' : 'Buff'
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function AddModal({ item, apiBase, onClose, onAdded }) {
  const [targetPrice, setTargetPrice] = useState('')
  const [recommendation, setRecommendation] = useState(null)
  const [status, setStatus] = useState('loading')
  const [saveError, setSaveError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!item) return undefined

    setTargetPrice('')
    setRecommendation(null)
    setSaveError('')
    setStatus('loading')

    const controller = new AbortController()
    fetch(`${apiBase}/api/recommend/${item.goods_id}?source=${encodeURIComponent(item.source || 'buff')}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error('No recommendation')
        return response.json()
      })
      .then((data) => {
        setRecommendation(data)
        if (Number.isFinite(Number(data.recommended_target))) {
          setTargetPrice(Number(data.recommended_target).toFixed(2))
        }
        setStatus('ready')
      })
      .catch((error) => {
        if (error.name === 'AbortError') return
        setStatus('unavailable')
      })

    return () => controller.abort()
  }, [apiBase, item])

  const range = useMemo(() => {
    if (!recommendation) return null
    const low = Number(recommendation.low)
    const avg = Number(recommendation.avg)
    const high = Number(recommendation.high)
    const target = Number(targetPrice || recommendation.recommended_target)
    if (![low, avg, high].every(Number.isFinite)) return null
    const spread = high - low || 1
    const position = (value) => `${clamp(((value - low) / spread) * 100, 0, 100)}%`
    return { low, avg, high, target, position }
  }, [recommendation, targetPrice])

  const submit = async (event) => {
    event.preventDefault()
    if (!item || saving) return

    setSaving(true)
    setSaveError('')
    try {
      const response = await fetch(`${apiBase}/api/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          goods_id: item.goods_id,
          source: item.source || 'buff',
          name: item.name,
          target_price: Number.parseFloat(targetPrice) || 0,
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || 'Could not add item')
      onAdded(data.item)
    } catch (error) {
      setSaveError(error.message)
    } finally {
      setSaving(false)
    }
  }

  if (!item) return null

  return (
    <motion.div
      className="modal-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onMouseDown={onClose}
    >
      <motion.form
        className="add-modal"
        initial={{ opacity: 0, y: 22, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 18, scale: 0.98 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
        onMouseDown={(event) => event.stopPropagation()}
        onSubmit={submit}
      >
        <div className="modal-heading">
          <div>
            <span className={`market-chip ${item.source === 'youpin' ? 'chip-uu' : 'chip-buff'}`}>{sourceLabel(item.source)}</span>
            <h2>Add to watchlist</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close add modal">×</button>
        </div>

        <div className="modal-item-row">
          <div className="modal-item-icon">
            {item.icon ? <img src={item.icon} alt="" /> : <span>CS2</span>}
          </div>
          <div>
            <strong>{item.name}</strong>
            <span>Current {formatPrice(item.price)} · #{item.goods_id}</span>
          </div>
        </div>

        <section className="recommend-card">
          <div className="recommend-header">
            <span>Recommended monitoring range</span>
            <strong>{status === 'loading' ? 'Loading…' : status === 'ready' ? formatPrice(recommendation?.recommended_target) : 'Unavailable'}</strong>
          </div>

          {range ? (
            <>
              <div className="range-track">
                <span className="range-fill" />
                <span className="range-marker range-low" style={{ left: range.position(range.low) }} />
                <span className="range-marker range-avg" style={{ left: range.position(range.avg) }} />
                <span className="range-marker range-high" style={{ left: range.position(range.high) }} />
                <span className="range-marker range-target" style={{ left: range.position(range.target) }} />
              </div>
              <div className="range-values">
                <span>7d low <strong>{formatPrice(range.low)}</strong></span>
                <span>Avg <strong>{formatPrice(range.avg)}</strong></span>
                <span>7d high <strong>{formatPrice(range.high)}</strong></span>
              </div>
              <p>Suggested target is 10% below the 7-day low.</p>
            </>
          ) : (
            <p>Historical data is not available for this item yet. You can still set a manual target.</p>
          )}
        </section>

        <label className="field-label" htmlFor="target-price">Target price</label>
        <div className="target-input-row">
          <input
            id="target-price"
            type="number"
            min="0"
            step="0.01"
            value={targetPrice}
            onChange={(event) => setTargetPrice(event.target.value)}
            placeholder="Optional"
          />
          {recommendation?.recommended_target && (
            <button type="button" onClick={() => setTargetPrice(Number(recommendation.recommended_target).toFixed(2))}>
              Use recommended
            </button>
          )}
        </div>

        {saveError && <div className="form-error">{saveError}</div>}

        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
          <button type="submit" className="primary-button" disabled={saving}>{saving ? 'Adding…' : 'Add to watch'}</button>
        </div>
      </motion.form>
    </motion.div>
  )
}

export default AddModal
