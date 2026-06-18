function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

function Sparkline({ points = [], positive = true }) {
  const values = points.map(Number).filter(Number.isFinite).slice(-7)
  const width = 180
  const height = 54
  const padding = 6

  if (values.length < 2) {
    return (
      <div className="sparkline sparkline-muted" aria-label="No trend data">
        <svg viewBox={`0 0 ${width} ${height}`} role="img">
          <line x1="8" y1="27" x2="172" y2="27" stroke="currentColor" strokeDasharray="4 6" />
        </svg>
        <span>No trend yet</span>
      </div>
    )
  }

  const min = Math.min(...values)
  const max = Math.max(...values)
  const spread = max - min || 1
  const step = (width - padding * 2) / (values.length - 1)
  const coords = values.map((value, index) => {
    const x = padding + step * index
    const y = height - padding - ((value - min) / spread) * (height - padding * 2)
    return [x, y]
  })

  const linePath = coords.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`).join(' ')
  const areaPath = `${linePath} L ${coords.at(-1)[0].toFixed(2)} ${height - padding} L ${coords[0][0].toFixed(2)} ${height - padding} Z`
  const trendUp = values.at(-1) >= values[0]
  const colorClass = positive ? (trendUp ? 'spark-red' : 'spark-green') : (trendUp ? 'spark-green' : 'spark-red')

  return (
    <div className={`sparkline ${colorClass}`} aria-label={`Price trend from ${values[0]} to ${values.at(-1)}`}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        <path d={areaPath} className="spark-area" />
        <path d={linePath} className="spark-line" />
        {isFiniteNumber(values.at(-1)) && (
          <circle cx={coords.at(-1)[0]} cy={coords.at(-1)[1]} r="3" className="spark-dot" />
        )}
      </svg>
    </div>
  )
}

export default Sparkline
