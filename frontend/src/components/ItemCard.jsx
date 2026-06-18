import { useEffect, useMemo, useState } from 'react'
import { animate, motion, useMotionValue } from 'framer-motion'
import Sparkline from './Sparkline'

function isNumber(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

function formatPrice(value) {
  return isNumber(value) ? `¥${value.toFixed(2)}` : '—'
}

function sourceLabel(source) {
  return source === 'youpin' ? 'UU' : 'Buff'
}

function AnimatedPrice({ value, className = '' }) {
  const motionValue = useMotionValue(isNumber(value) ? value : 0)
  const [display, setDisplay] = useState(formatPrice(value))

  useEffect(() => {
    if (!isNumber(value)) {
      setDisplay('—')
      return undefined
    }

    const unsubscribe = motionValue.on('change', (latest) => {
      setDisplay(`¥${latest.toFixed(2)}`)
    })
    const controls = animate(motionValue, value, { duration: 0.55, ease: 'easeOut' })

    return () => {
      unsubscribe()
      controls.stop()
    }
  }, [motionValue, value])

  return <motion.span className={className}>{display}</motion.span>
}

function ItemCard({ item, history = [], onRemove, index = 0 }) {
  const buff = item.buff || null
  const youpin = item.youpin || null
  const buffLow = isNumber(buff?.low) ? buff.low : null
  const youpinLow = isNumber(youpin?.low) ? youpin.low : null
  const primary = item.source === 'youpin' ? youpin : buff || youpin
  const primaryLow = isNumber(primary?.low) ? primary.low : null
  const icon = buff?.icon || youpin?.icon || item.icon || ''
  const alerting = Boolean(item.alerting || item.alerted)
  const target = Number(item.target_price || 0)

  const trend = useMemo(() => history.map(Number).filter(Number.isFinite).slice(-7), [history])
  const trendDelta = trend.length > 1 ? trend.at(-1) - trend[0] : null
  const reachedTarget = target > 0 && isNumber(primaryLow) && primaryLow <= target

  return (
    <motion.article
      className={`watch-card ${alerting ? 'is-alerting' : ''}`}
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 18 }}
      transition={{ delay: index * 0.045, duration: 0.28, ease: 'easeOut' }}
      whileHover={{ scale: 1.012, y: -3 }}
      layout
    >
      <div className="watch-card-topline">
        <span className={`source-pill ${item.source === 'youpin' ? 'source-uu' : 'source-buff'}`}>
          {sourceLabel(item.source)} watch
        </span>
        <div className="card-controls">
          {alerting && <span className="alert-dot" title="Alert active" />}
          <button type="button" className="icon-button" onClick={() => onRemove(item.goods_id)} aria-label={`Remove ${item.name}`}>
            ×
          </button>
        </div>
      </div>

      <div className="item-identity">
        <div className="item-art">
          {icon ? <img src={icon} alt="" loading="lazy" /> : <span>CS2</span>}
        </div>
        <div>
          <h2 className="item-title">{item.name}</h2>
          <p className="item-meta">#{item.goods_id}</p>
        </div>
      </div>

      <div className="price-comparison" aria-label="Price comparison">
        <div className="price-cell">
          <span className="price-label buff-label">Buff</span>
          <AnimatedPrice value={buffLow} className="price-value" />
          <span className="price-subline">{buff?.count ? `${buff.count} listings` : 'market low'}</span>
        </div>
        <div className="price-cell">
          <span className="price-label uu-label">UU</span>
          <AnimatedPrice value={youpinLow} className="price-value" />
          <span className="price-subline">{youpin?.count ? `${youpin.count} listings` : 'market low'}</span>
        </div>
      </div>

      <div className="trend-row">
        <div>
          <span className="section-label">7-point trend</span>
          <strong className={trendDelta == null ? 'trend-neutral' : trendDelta <= 0 ? 'trend-good' : 'trend-bad'}>
            {trendDelta == null ? 'Waiting for data' : `${trendDelta <= 0 ? '▼' : '▲'} ${formatPrice(Math.abs(trendDelta))}`}
          </strong>
        </div>
        <Sparkline points={trend} />
      </div>

      <div className="card-footer">
        {target > 0 ? (
          <span className={`target-badge ${reachedTarget ? 'target-hit' : ''}`}>
            Target {formatPrice(target)}{reachedTarget ? ' reached' : ''}
          </span>
        ) : (
          <span className="target-empty">No target set</span>
        )}
        {isNumber(item.price_diff) && <span className="diff-note">Δ {formatPrice(item.price_diff)}</span>}
      </div>
    </motion.article>
  )
}

export default ItemCard
