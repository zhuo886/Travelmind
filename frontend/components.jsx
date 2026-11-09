// components.jsx — 行程条目 / 地图 / 运行轨道

/* ── 运行轨道（规划中） ───────────────────────────── */
// 旅程站点：后端多个节点可映射到同一站（NODE_TO_STEP），
// planner⇄reviewer / planner⇄time_check 多轮循环时只前进不后退，
// 轮次细节由实时文案（stage label）展示。
const JOURNEY_STEPS = [
  { key: "intent",            label: "理解出行意图",       detail: "目的地 / 日期 / 偏好 · 查询天气预报" },
  { key: "query_rewrite",     label: "结合画像优化查询",   detail: "个性化改写中" },
  { key: "attraction_search", label: "景点候选检索",      detail: "建立与补充候选池" },
  { key: "plan_review",       label: "景点与餐厅联合规划", detail: "联合时间轴 · 路线核验与审核" },
  { key: "time_check",        label: "核查开放时间",        detail: "逐景点核对营业时段" },
  { key: "enrichment",        label: "整理行程与游玩贴士",  detail: "保留已规划的用餐安排" },
  { key: "finalize",          label: "生成最终行程",         detail: "即将完成…" },
];
// 后端节点名 → 旅程站点 key
const NODE_TO_STEP = {
  intent:            "intent",
  query_rewrite:     "query_rewrite",
  weather_search:    "query_rewrite",
  main_meal_search:  "query_rewrite",
  attraction_search: "attraction_search",
  candidate_react:   "attraction_search",
  candidate_search:  "attraction_search",
  candidate_validator: "attraction_search",
  candidate_ready:   "attraction_search",
  planner:           "plan_review",
  reviewer:          "plan_review",
  time_check:        "time_check",
  meal_search:       "enrichment",
  meal_recommend:    "enrichment",
  meal_enrichment:   "enrichment",
  main_meal_output:  "enrichment",
  route_distance_check: "plan_review",
  risk_gate:         "plan_review",
  spot_tips:         "enrichment",
  finalize:          "finalize",
  finalize_direct:   "finalize",
};
Object.assign(window, { JOURNEY_STEPS, NODE_TO_STEP });

function JourneyLoading({ steps, activeNode, doneNodes }) {
  const doneSet = new Set(doneNodes || []);
  const N = steps.length;
  return (
    <div className="run-track" aria-label="编排进度">
      <div className="run-track-inner">
        {steps.map((s, i) => {
          const isDone = doneSet.has(s.key);
          const isActive = s.key === activeNode;
          return (
            <div
              key={s.key}
              className={`run-knot${isDone ? " done" : isActive ? " active" : ""}`}
              title={s.detail}
            >
              <span className="run-knot-no">{isDone ? "✓" : String(i + 1).padStart(2, "0")}</span>
              <span className="run-knot-dot" />
              <span className="run-knot-label">{s.label}</span>
            </div>
          );
        })}
      </div>
      <span className="tm-eyebrow" style={{ display: "block", marginTop: 12 }}>
        {doneSet.size} / {N} 阶段完成
      </span>
    </div>
  );
}

/* ── 地图 ──────────────────────────────────────────── */
// SVG 示意地图：高德 JS 地图加载前的占位，以及未配置 AMAP_JS_KEY / 加载失败时的降级兜底
function DayMap({ mapPoints, dayKey }) {
  const pts = mapPoints || [];
  const poly = pts.map((p) => `${p.x},${p.y}`).join(" ");

  return (
    <div className="map-canvas">
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" key={dayKey}>
        <g stroke="var(--line-2)" strokeWidth=".25">
          {[15, 30, 45, 60, 75, 90].map((v) => (
            <React.Fragment key={v}>
              <line x1={v + 4} y1="-5" x2={v - 8} y2="105" />
              <line x1="-5" y1={v} x2="105" y2={v - 6} />
            </React.Fragment>
          ))}
        </g>
        <path d="M-5 84 Q 24 72 46 84 T 105 80 L 105 105 L -5 105 Z" fill="var(--map-water)" />
        <path d="M58 -5 q 10 18 -2 32 q -8 11 2 22" fill="none" stroke="var(--map-water)" strokeWidth="5" strokeLinecap="round" opacity=".8" />
        <ellipse cx="22" cy="22" rx="16" ry="11" fill="var(--map-park)" />
        <ellipse cx="84" cy="38" rx="13" ry="9" fill="var(--map-park)" />
        <ellipse cx="44" cy="62" rx="9" ry="6" fill="var(--map-park)" opacity=".8" />
        {poly && (
          <polyline
            points={poly} fill="none"
            stroke="var(--accent)" strokeWidth=".8"
            strokeDasharray="2 1.9" strokeLinecap="round" strokeLinejoin="round"
            style={{ animation: "routeDash 30s linear infinite" }}
          />
        )}
        <style>{`@keyframes routeDash { to { stroke-dashoffset: -92; } }`}</style>
        {pts.map((p, i) => {
          // 全天统一编号：住宿、景点、午餐/晚餐都占号，与时间轴顺序一致
          const seq = i + 1;
          const kind = p.kind || "attraction";
          const fill = kind === "meal" ? "var(--second)" : kind === "hotel" ? "var(--ink)" : "var(--accent)";
          return (
            <g key={`${dayKey}-${i}`} className="map-pin-pop" style={{ "--pin-delay": `${i * 0.12 + 0.1}s`, transformOrigin: `${p.x}px ${p.y}px` }}>
              {kind === "attraction" ? (
                <circle cx={p.x} cy={p.y} r="3.4" fill={fill} />
              ) : (
                <rect
                  x={p.x - 3.1} y={p.y - 3.1} width="6.2" height="6.2"
                  rx={kind === "meal" ? 0.6 : 1.2}
                  fill={fill}
                  transform={kind === "meal" ? `rotate(45 ${p.x} ${p.y})` : undefined}
                />
              )}
              <text
                x={p.x} y={p.y + 1.5} textAnchor="middle"
                fontSize="4" fontWeight="700" fill="#fff" fontFamily="var(--font-mono)"
              >{seq}</text>
              <text className="map-pin-label" x={p.x} y={p.y - 5.2} textAnchor="middle" style={{ fontSize: "3.4px" }}>{p.label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function MapPanel({ day, dayIdx, navPair, onNavClear }) {
  const amapRef = React.useRef(null);
  // null=尝试加载中（显示 SVG 占位） true=高德地图就绪 false=降级 SVG
  const [amapReady, setAmapReady] = React.useState(null);
  const hasGeo = (day.mapPoints || []).some(p => p.lat && p.lng);

  // 点位签名：优化路线后同一天的点位顺序变化时也要重画地图
  const ptsSig = (day.mapPoints || []).map(p => p.name).join("|");
  // initAmapForDay 本身就画了一次全天路线，避免首屏再调一次 restoreFullRoute
  const drawnRef = React.useRef(false);

  React.useEffect(() => {
    if (!hasGeo) { setAmapReady(false); return; }
    let alive = true;
    drawnRef.current = false;
    initAmapForDay(amapRef.current, day.mapPoints).then(ok => { if (alive) setAmapReady(ok); });
    return () => { alive = false; };
  }, [dayIdx, hasGeo, ptsSig]);

  // 导航对 / 恢复全日路线
  React.useEffect(() => {
    if (amapReady !== true) return;
    if (navPair) {
      drawNavPairRoute(amapRef.current, navPair.from, navPair.to);
      drawnRef.current = true;
      return;
    }
    if (!drawnRef.current) { drawnRef.current = true; return; }
    restoreFullRoute(amapRef.current, day.mapPoints);
  }, [navPair, amapReady]); // eslint-disable-line

  // 组件卸载时销毁地图实例
  React.useEffect(() => () => destroyAmap(amapRef.current), []);

  return (
    <div className="map-frame">
      <div className="map-head">
        <span className="map-title">Day {dayIdx + 1} · 路线图</span>
        {navPair && onNavClear && (
          <button className="map-clear" onClick={onNavClear}>✕ 退出导航</button>
        )}
        {amapReady !== true && !navPair && <span className="map-note">点位示意图</span>}
      </div>
      <div className="map-stage">
        <DayMap mapPoints={day.mapPoints} dayKey={dayIdx} />
        {hasGeo && (
          <div
            ref={amapRef}
            className="amap-host"
            style={{
              position: "absolute", inset: 0,
              opacity: amapReady === true ? 1 : 0,
              pointerEvents: amapReady === true ? "auto" : "none",
              transition: "opacity .4s ease",
            }}
          />
        )}
      </div>
      <div className="map-legend">
        <span><span className="legend-dot" style={{ background: "var(--ink)", borderRadius: 1 }}></span>住宿</span>
        <span><span className="legend-dot" style={{ background: "var(--accent)", borderRadius: "50%" }}></span>景点</span>
        <span><span className="legend-dot" style={{ background: "var(--second)", borderRadius: 0, transform: "rotate(45deg)" }}></span>餐厅</span>
        <span style={{ marginLeft: "auto" }}>序号即当天游览顺序</span>
      </div>
    </div>
  );
}

/* ── 条目通用 ──────────────────────────────────────── */
function photoUrl(seed, w = 640, h = 440) {
  return `https://picsum.photos/seed/${encodeURIComponent(seed)}/${w}/${h}`;
}
Object.assign(window, { photoUrl });

function Thumb({ photo, seed, alt }) {
  const [err, setErr] = React.useState(false);
  const src = photo || (seed ? photoUrl(seed, 360, 280) : null);
  if (!src || err) return <div className="thumb is-empty" aria-label={alt}>—</div>;
  return (
    <div className="thumb" style={{ backgroundImage: `url('${src}')` }} aria-label={alt}>
      <img src={src} alt="" style={{ display: "none" }} onError={() => setErr(true)} />
    </div>
  );
}

const PERIOD = {
  morning:   { label: "上午" },
  afternoon: { label: "下午" },
  evening:   { label: "夜间" },
};

// 站点间通行标注：≤3km 按步行（约 4km/h）估时，更远建议乘车
function walkNote(dist) {
  if (dist == null || !(dist > 0)) return null;
  const d = Number(dist);
  if (d <= 3) return `步行 ${d} km · 约 ${Math.max(1, Math.round(d * 15))} 分钟`;
  return `相距 ${d} km · 建议乘车`;
}

function WalkIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M13 4a2 2 0 1 0 0-.1M7 21l3-4.5L8 12l2.5-3 2.5 2 3 1" />
    </svg>
  );
}

function AttractionCard({ item, onNearby }) {
  const p = PERIOD[item.period] || PERIOD.morning;
  return (
    <div className="spot">
      <div className="spot-body">
        <div className="spot-head">
          <h4 className="spot-name">{item.name}</h4>
          <span className="flag">{p.label}</span>
        </div>
        <div className="spot-meta">
          {item.start && <span>{item.start}{item.end ? ` – ${item.end}` : ""}</span>}
          {item.rating != null && <span className="star">★ {Number(item.rating).toFixed(1)}</span>}
          {item.cost != null && (
            <span>{Number(item.cost) === 0 ? "免费" : `¥${item.cost}/人`}</span>
          )}
          {item.open && <span>开放 {item.open}</span>}
        </div>
        {item.ticketInfo && (
          <div className="spot-src">
            <span>{item.ticketInfo.price_label}</span>
            {item.ticketInfo.source_url ? (
              <a href={item.ticketInfo.source_url} target="_blank" rel="noreferrer">
                来源：{item.ticketInfo.source_name}
              </a>
            ) : <span>来源：{item.ticketInfo.source_name}</span>}
            <span>
              {item.ticketInfo.live_query ? "本次联网查询" : "核验于"} {item.ticketInfo.queried_at
                ? new Date(item.ticketInfo.queried_at).toLocaleString("zh-CN", { hour12: false })
                : item.ticketInfo.verified_at}
            </span>
            {item.ticketInfo.note && <small>{item.ticketInfo.note}</small>}
          </div>
        )}
        {item.address && <div className="spot-addr">{item.address}</div>}
        {item.tel && <div className="spot-addr">电话 {item.tel}</div>}
        {item.guide && (
          <div className="spot-guide">
            <div className="spot-guide-title">景区内怎么走</div>
            {item.guide.entrance && <div>入口 · {item.guide.entrance}</div>}
            {item.guide.visit_order?.length > 0 && (
              <div>顺序 · {item.guide.visit_order.join(" → ")}</div>
            )}
            {item.guide.recommended_duration && (
              <div>建议时长 · {item.guide.recommended_duration}</div>
            )}
          </div>
        )}
        {item.note && <div className="spot-note">{item.note}</div>}
        {onNearby && item.location && (
          <button className="spot-nearby" onClick={() => onNearby(item)}>周边搜索 →</button>
        )}
      </div>
      <Thumb photo={item.photo} seed={item.seed} alt={item.name} />
    </div>
  );
}

function MealCard({ item }) {
  const label = item.type === "lunch" ? "午餐" : "晚餐";
  if (item.no_restaurant) {
    return (
      <div className="meal is-empty">
        <div className="spot-body">
          <div className="spot-head">
            <h4 className="spot-name">{label} · 该时段附近暂无餐厅数据</h4>
          </div>
          <div className="spot-addr">建议出发前自行规划{label}，或让我换一片区域再找找。</div>
        </div>
      </div>
    );
  }
  return (
    <div className="meal">
      <div className="spot-body">
        <div className="spot-head">
          <h4 className="spot-name">{item.name}</h4>
          <span className="flag flag--meal">{label}</span>
        </div>
        <div className="spot-meta">
          {item.rating != null && <span className="star">★ {Number(item.rating).toFixed(1)}</span>}
          {item.cost && <span>¥{item.cost}/人</span>}
          {item.category && <span>{item.category}</span>}
        </div>
        {item.costInfo && (
          <div className="spot-src">
            <span>{item.costInfo.price_label}</span>
            <span>{item.costInfo.source_name}</span>
            {item.costInfo.observed_at && <span>记录于 {item.costInfo.observed_at}</span>}
            {item.costInfo.estimate && <span>估算值</span>}
          </div>
        )}
        {item.open && <div className="spot-addr">营业 {item.open}</div>}
        {item.addr && <div className="spot-addr">{item.addr}</div>}
        {item.tel && <div className="spot-addr">电话 {item.tel}</div>}
        {item.reason && <div className="meal-reason">{item.reason}</div>}
      </div>
      <Thumb photo={item.photo} seed={item.seed} alt={item.name} />
    </div>
  );
}

function previewTransportEstimate(dist) {
  const d = Number(dist);
  if (!(d > 0)) return null;
  if (d <= 1.2) {
    const mins = Math.max(3, Math.round(d / 4.5 * 60));
    return { mode: "walk", mode_label: "步行", duration_min: mins, estimated_cost: 0,
      instruction: `先按距离估算步行约 ${mins} 分钟。`, source: "estimate" };
  }
  if (d <= 12) {
    return { mode: "transit", mode_label: "地铁/公交",
      duration_min: Math.max(18, Math.round(d / 22 * 60 + 12)),
      estimated_cost: Math.min(8, Math.max(2, 2 + Math.ceil(d / 6))),
      instruction: "正在补充具体线路，当前先按距离显示公共交通估算。", source: "estimate" };
  }
  return { mode: "taxi_or_car", mode_label: "打车/租车",
    duration_min: Math.max(25, Math.round(d / 28 * 60 + 5)),
    estimated_cost: Math.round(13 + Math.max(0, d - 3) * 2.3),
    instruction: "当前先按距离显示打车估算。", source: "estimate" };
}

// 导航行：夹在任意相邻两个 item 之间
function NavRow({ itemA, itemB, city, onNav, isActive }) {
  const hasCoords = itemA?.location?.lat && itemA?.location?.lng
    && itemB?.location?.lat && itemB?.location?.lng;
  const [loadedTravel, setLoadedTravel] = React.useState(null);
  const [routeStatus, setRouteStatus] = React.useState("idle");
  const [routeError, setRouteError] = React.useState("");
  const travel = loadedTravel || itemB.travel || previewTransportEstimate(itemB.dist);
  React.useEffect(() => {
    let alive = true;
    if (hasCoords && itemB.travel?.source !== "amap") {
      setRouteStatus("loading");
      setRouteError("");
      fetchTransportPlan(itemA.location, itemB.location, city, itemA.name, itemB.name)
        .then(plan => { if (alive) { setLoadedTravel(plan); setRouteStatus("done"); } })
        .catch(error => {
          if (!alive) return;
          let message = error?.message || "真实路线查询失败";
          if (error?.status === 404) message = "路线接口未加载，请重启后端服务";
          else if (error?.status === 401) message = "登录状态已过期，请重新登录";
          setRouteError(message);
          setRouteStatus("failed");
        });
    }
    return () => { alive = false; };
  }, [itemA.name, itemB.name, city, itemB.travel?.source]); // eslint-disable-line
  if (!hasCoords) return null;
  const dist = itemB.dist;
  const routeMode = travel?.mode === "walk" ? "walk" : travel?.mode === "transit" ? "bus" : "car";
  const amapUrl = `https://uri.amap.com/navigation?from=${itemA.location.lng},${itemA.location.lat},${encodeURIComponent(itemA.name)}&to=${itemB.location.lng},${itemB.location.lat},${encodeURIComponent(itemB.name)}&mode=${routeMode}&policy=1&src=travelmind&coordinate=gaode&callnative=0`;
  return (
    <div className="nav-row">
      <div className="tl-time nav-dist">{dist ? `${dist} km` : ""}</div>
      <div className="tl-rail">
        <span
          className="tl-dot is-nav"
          style={isActive ? { background: "var(--accent)", borderColor: "var(--accent)" } : undefined}
        />
      </div>
      <div className="nav-body">
        <div className="nav-line">
          <span className="nav-mode">{travel?.mode_label || "路线"}</span>
          <span className="nav-path">{itemA.name} → {itemB.name}</span>
          {travel && (
            <span className="nav-metrics">
              约 {travel.duration_min} 分钟{Number(travel.estimated_cost) > 0 ? ` · ¥${travel.estimated_cost}/人` : ""}
            </span>
          )}
        </div>
        {travel?.instruction && <div className="nav-inst">{travel.instruction}</div>}
        {routeStatus === "loading" && (
          <div className="nav-status">正在后台补充具体线路，当前先显示估算方案…</div>
        )}
        {routeStatus === "failed" && (
          <div className="nav-status is-failed">{routeError}，已保留估算方案。</div>
        )}
        <div className="nav-actions">
          <button
            className={`nav-btn${isActive ? " active" : ""}`}
            onClick={() => onNav({ from: itemA.location, to: itemB.location })}
          >地图预览</button>
          <a className="nav-btn" href={amapUrl} target="_blank" rel="noreferrer">高德实时线路</a>
        </div>
      </div>
    </div>
  );
}

function DayBudget({ budget, mobilityAdvice }) {
  if (!budget) return null;
  return (
    <section className="budget" aria-label="当日费用估算">
      <div className="budget-head">
        <div>
          <div className="tm-eyebrow">当日人均费用</div>
          <div className="budget-total">¥{Number(budget.estimated_subtotal ?? budget.known_subtotal ?? 0).toFixed(0)}</div>
        </div>
        <span className="flag">估算</span>
      </div>
      <div className="budget-grid">
        <div className="budget-cell">
          <span>门票</span>
          <b>¥{Number(budget.ticket_known || 0).toFixed(0)}</b>
        </div>
        <div className="budget-cell">
          <span>餐饮</span>
          <b>
            ¥{Number((budget.meal_known || 0) + (budget.meal_estimated || 0)).toFixed(0)}
            {budget.meal_estimated > 0 && <small>含估算 ¥{Number(budget.meal_estimated).toFixed(0)}</small>}
          </b>
        </div>
        <div className="budget-cell">
          <span>交通</span>
          <b>¥{Number(budget.transport_estimated || 0).toFixed(0)}</b>
        </div>
      </div>
      {budget.unknown_items?.length > 0 && (
        <div className="budget-note">
          未计价：{budget.unknown_items.slice(0, 4).join("、")}{budget.unknown_items.length > 4 ? "等" : ""}
        </div>
      )}
      {mobilityAdvice && <div className="budget-note">租车提示：{mobilityAdvice}</div>}
      {budget.note && <div className="budget-note">{budget.note}</div>}
    </section>
  );
}

function HotelCard({ item }) {
  const info = item.hotelInfo || {};
  const price = info.nightly_price ?? item.cost;
  return (
    <div className="hotel">
      <div className="spot-body">
        <div className="spot-head">
          <h4 className="spot-name">{item.name}</h4>
          <span className="flag">出发点</span>
        </div>
        <div className="spot-meta">
          {item.rating != null && <span className="star">★ {Number(item.rating).toFixed(1)}</span>}
          {price != null && <span>约 ¥{Number(price).toFixed(0)}/间夜</span>}
        </div>
        {item.address && <div className="spot-addr">{item.address}</div>}
        <div className="hotel-note">当天路线从酒店出发；价格来自本次高德查询，预订前请复核。</div>
      </div>
    </div>
  );
}

// 时间轴：左侧时间槽 + 轴线，相邻两项之间插入导航行
function Timeline({ items, city, onNav, activeNavKey }) {
  return (
    <div className="tl">
      {items.map((item, i) => {
        const isMeal = item.type !== "attraction" && item.type !== "hotel";
        const seqCls = item.type === "hotel" ? " is-hotel" : isMeal ? " is-meal" : " is-spot";
        const prevItem = i > 0 ? items[i - 1] : null;
        const navKey = i > 0 ? String(i) : null;
        return (
          <React.Fragment key={i}>
            {i > 0 && onNav && (
              <NavRow
                itemA={prevItem}
                itemB={item}
                city={city}
                onNav={(pair) => onNav(activeNavKey === navKey ? null : navKey, pair)}
                isActive={activeNavKey === navKey}
              />
            )}
            <div className="tl-row">
              <div className="tl-time">{isMeal ? "" : (item.start || "")}</div>
              {/* 序号与右侧地图标记一致：住宿、景点、午餐/晚餐都占号 */}
              <div className="tl-rail"><span className={`tl-seq${seqCls}`}>{i + 1}</span></div>
              <div className="tl-content">
                {item.type === "hotel"
                  ? <HotelCard item={item} />
                  : isMeal
                  ? <MealCard item={item} />
                  : <AttractionCard item={item} onNearby={onNav ? (it) => onNav("nearby:" + i, null, it) : undefined} />
                }
              </div>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}

/* ── 候选景点池 ──────────────────────────────────── */
function RecommendStrip({ candidates, editing }) {
  const [detail, setDetail] = React.useState(null);

  if (!candidates || !candidates.length) return null;
  return (
    <div className="cand">
      <div className="cand-head">
        <span className="tm-eyebrow">候选景点池</span>
        {editing && <span className="cand-hint">拖入时间轴可替换景点</span>}
      </div>
      <div className="cand-scroll">
        {candidates.map((c, i) => (
          <div
            key={i}
            className={`cand-card${editing ? " is-draggable" : ""}${detail === c ? " is-active" : ""}`}
            draggable={editing}
            onDragStart={editing ? (e) => {
              e.dataTransfer.setData("application/json", JSON.stringify(c));
              e.dataTransfer.effectAllowed = "copy";
            } : undefined}
            onClick={() => setDetail(detail === c ? null : c)}
            role="button"
            tabIndex={0}
          >
            <div
              className="cand-thumb"
              style={c.photo ? { backgroundImage: `url('${c.photo}')` } : undefined}
            />
            <div className="cand-name">{c.name}</div>
            <div className="cand-meta">
              {c.rating != null && <span>★ {Number(c.rating).toFixed(1)}</span>}
            </div>
          </div>
        ))}
      </div>
      {detail && (
        <div className="cand-pop">
          <button className="cand-pop-close" onClick={() => setDetail(null)}>✕</button>
          {detail.photo && (
            <div className="cand-pop-img" style={{ backgroundImage: `url('${detail.photo}')` }} />
          )}
          <div>
            <div className="cand-pop-name">{detail.name}</div>
            {detail.rating != null && <div className="cand-pop-row"><span>评分</span><span>{Number(detail.rating).toFixed(1)} 分</span></div>}
            {detail.address && <div className="cand-pop-row"><span>位置</span><span>{detail.address}</span></div>}
            {detail.open_time && <div className="cand-pop-row"><span>开放</span><span>{detail.open_time}</span></div>}
            {detail.cost && <div className="cand-pop-row"><span>门票</span><span>¥{detail.cost}/人</span></div>}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 周边搜索弹层 ────────────────────────────────── */
function NearbySearchModal({ location, name, onClose, onPickMeal }) {
  const [tab, setTab] = React.useState("attraction");
  const [radius, setRadius] = React.useState(1500);
  const [results, setResults] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState("");

  const doSearch = async (t, r) => {
    setLoading(true); setErr(""); setResults(null);
    try {
      const res = await searchNearby(location.lat, location.lng, t === "attraction" ? "风景名胜" : "餐饮服务", r);
      setResults(res);
      if (!res.length) setErr("附近暂无数据，试试调大半径");
    } catch (e) { setErr(e.message || "搜索失败"); }
    finally { setLoading(false); }
  };

  React.useEffect(() => { doSearch(tab, radius); }, []); // eslint-disable-line

  const switchTab = (t) => { setTab(t); doSearch(t, radius); };
  const changeRadius = (r) => { setRadius(r); doSearch(tab, r); };

  return (
    <div className="tm-scrim" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="tm-sheet tm-sheet--wide">
        <button className="tm-close" onClick={onClose} aria-label="关闭">✕</button>
        <div className="tm-sheet-title">{name} · 周边</div>
        <div className="tm-sheet-sub">按步行半径搜索附近的景点或餐厅，可直接替换当天用餐。</div>
        <div className="tm-tabs">
          <button className={`tm-tab${tab === "attraction" ? " active" : ""}`} onClick={() => switchTab("attraction")}>景点</button>
          <button className={`tm-tab${tab === "restaurant" ? " active" : ""}`} onClick={() => switchTab("restaurant")}>餐厅</button>
        </div>
        <div className="radius-row">
          {[500, 1000, 1500, 3000].map(r => (
            <button key={r} className={`radius-btn${radius === r ? " active" : ""}`} onClick={() => changeRadius(r)}>{r}m</button>
          ))}
        </div>
        {loading && <div className="poi-err">搜索中…</div>}
        {err && <div className="poi-err">{err}</div>}
        <div className="poi-list">
          {(results || []).map((p, i) => (
            <div key={i} className="poi-item">
              <div className="poi-item-name">{p.name}</div>
              <div className="poi-item-meta">
                {p.rating != null && <span>★ {Number(p.rating).toFixed(1)}</span>}
                {p.distance != null && <span>{p.distance}m</span>}
                {p.address && <span>{p.address}</span>}
              </div>
              {tab === "restaurant" && onPickMeal && (
                <div className="nearby-actions">
                  <button className="nearby-btn" onClick={() => onPickMeal(p, "lunch")}>设为午餐</button>
                  <button className="nearby-btn" onClick={() => onPickMeal(p, "dinner")}>设为晚餐</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, {
  JourneyLoading, DayMap, MapPanel, Timeline, NavRow, Thumb,
  RecommendStrip, NearbySearchModal,
  walkNote, WalkIcon,
});
