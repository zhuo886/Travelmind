// edit.jsx — 行程手动编辑：编辑态时间轴 / 拖拽 / 搜索弹层 / 时间编辑

/* ── 纯函数工具 ──────────────────────────────── */

// 编辑顺序变化后清除旧路线。保存时由后端并发查询高德道路距离后回填。
function recalcDayDists(timeline) {
  const valid = (loc) => loc && typeof loc.lat === "number" && typeof loc.lng === "number";
  timeline.forEach((item, i) => {
    if (i === 0) { delete item.dist_from_prev_km; delete item.travel_from_prev; return; }
    const prev = timeline[i - 1].location, cur = item.location;
    if (valid(prev) && valid(cur)) {
      delete item.dist_from_prev_km;
      item.travel_from_prev = {
        from: timeline[i - 1].name || "上一站", to: item.name || "下一站",
        mode: "unavailable", mode_label: "路线待核验", distance_km: null,
        duration_min: null, source: "pending", estimate: true,
      };
    } else {
      delete item.dist_from_prev_km;
      delete item.travel_from_prev;
    }
  });
}

// 拖拽换序：时间段留在位置上不跟卡走——
// 先记录原顺序中各景点的时段，移动后按新顺序把时段逐个套回景点
// 调用后须紧接 recalcDayDists(newTimeline) 清除已经失效的道路距离
function reorderKeepTimes(timeline, from, to) {
  const slots = timeline
    .filter(it => it.type === "attraction")
    .map(it => ({ start_time: it.start_time, end_time: it.end_time, period: it.period }));
  const arr = timeline.slice();
  const [moved] = arr.splice(from, 1);
  arr.splice(to, 0, moved);
  let si = 0;
  return arr.map(it => (it.type === "attraction" ? { ...it, ...slots[si++] } : it));
}

/* ── POI 搜索弹层 ─────────────────────────────────── */
function PoiSearchModal({ city, kind, title, onPick, onClose }) {
  const [kw, setKw] = React.useState("");
  const [results, setResults] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState("");

  const search = async () => {
    if (!kw.trim() || loading) return;
    setLoading(true); setErr("");
    try {
      const r = await searchPoi(city, kw.trim(), kind);
      setResults(r);
      if (!r.length) setErr("没找到，换个关键词试试");
    } catch (e) { setErr(e.message || "搜索失败"); }
    finally { setLoading(false); }
  };

  return (
    <div className="tm-scrim" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="tm-sheet tm-sheet--wide">
        <button className="tm-close" onClick={onClose} aria-label="关闭">✕</button>
        <div className="tm-sheet-title">{title}</div>
        <div className="tm-sheet-sub">在「{city}」范围内搜索，选中后会写回当天时间轴。</div>
        <div className="poi-search-bar">
          <input className="tm-input" autoFocus value={kw}
            placeholder={kind === "restaurant" ? "输入餐厅名或菜系，回车搜索" : "输入景点名，回车搜索"}
            onChange={(e) => setKw(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()} />
          <button className="tm-btn tm-btn--primary tm-btn--sm" onClick={search} disabled={loading || !kw.trim()}>
            {loading ? "搜索中…" : "搜索"}
          </button>
        </div>
        {err && <div className="poi-err">{err}</div>}
        <div className="poi-list">
          {(results || []).map((p, i) => (
            <button key={i} className="poi-item" onClick={() => onPick(p)}>
              <div className="poi-item-name">{p.name}</div>
              <div className="poi-item-meta">
                {p.rating != null && <span>★ {Number(p.rating).toFixed(1)}</span>}
                {p.cost && <span>¥{p.cost}/人</span>}
                {p.open_time && <span>开放 {p.open_time}</span>}
                {p.address && <span>{p.address}</span>}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── 时间段编辑器（仅景点） ─────────────────────────── */
function TimeRangeEditor({ start, end, onCommit }) {
  const [st, setSt] = React.useState(start || "");
  const [et, setEt] = React.useState(end || "");
  const [bad, setBad] = React.useState(false);

  // 撤销/重做会改变传入的时间，同步回本地输入
  React.useEffect(() => { setSt(start || ""); setEt(end || ""); setBad(false); }, [start, end]);

  const commit = () => {
    if (st && et && st >= et) { setBad(true); return; }
    setBad(false);
    if (st !== (start || "") || et !== (end || "")) onCommit(st || null, et || null);
  };

  return (
    <span className={`time-edit ${bad ? "bad" : ""}`}>
      <input type="time" value={st} onChange={(e) => setSt(e.target.value)} onBlur={commit} />
      <span>–</span>
      <input type="time" value={et} onChange={(e) => setEt(e.target.value)} onBlur={commit} />
      {bad && <span className="time-edit-err">开始须早于结束</span>}
    </span>
  );
}

/* ── 编辑态条目 ─────────────────────────────────────── */
function EditCard({ raw, onReplace, onDelete, onTimeChange, onDropCandidate }) {
  const isAttr = raw.type === "attraction";
  const mealLabel = isAttr ? null : raw.type === "lunch" ? "午餐" : "晚餐";
  return (
    <div
      className={`ed-card${isAttr ? "" : " is-meal"}`}
      onDragOver={isAttr && onDropCandidate ? (e) => { e.preventDefault(); e.currentTarget.classList.add("drag-over"); } : undefined}
      onDragLeave={isAttr && onDropCandidate ? (e) => { e.currentTarget.classList.remove("drag-over"); } : undefined}
      onDrop={isAttr && onDropCandidate ? (e) => {
        e.preventDefault();
        e.currentTarget.classList.remove("drag-over");
        try {
          const candidate = JSON.parse(e.dataTransfer.getData("application/json"));
          if (candidate?.name) onDropCandidate(candidate);
        } catch {}
      } : undefined}
    >
      <span className="drag-grip" title="拖拽调整顺序">⠿</span>
      <div className="ed-body">
        <div className="ed-title">
          <span>{raw.name || `${mealLabel || "条目"}（待安排）`}</span>
          {mealLabel && <span className="flag flag--meal">{mealLabel}</span>}
        </div>
        <div className="ed-meta">
          {isAttr && <TimeRangeEditor start={raw.start_time} end={raw.end_time} onCommit={onTimeChange} />}
          {raw.rating != null && <span>★ {Number(raw.rating).toFixed(1)}</span>}
          {!isAttr && raw.cost && <span>¥{raw.cost}/人</span>}
          {isAttr && raw.open_time && <span>开放 {raw.open_time}</span>}
        </div>
      </div>
      <div className="ed-acts">
        <button className="ed-act" onClick={onReplace}>↔ 更换</button>
        <button className="ed-act is-danger" onClick={onDelete} title="删除（可撤销）">✕</button>
      </div>
    </div>
  );
}

/* ── 可拖拽时间轴 ───────────────────────────────────── */
// ver：编辑版本号。每次 draft 变化 +1，靠 key 强制重挂载列表，
// 保证 Sortable 动过的 DOM 与 React state 重新对齐（SortableJS×React 标准做法）。
function EditableTimeline({ rawTimeline, ver, onReorder, onReplace, onDelete, onTimeChange, onAdd, onDropCandidate }) {
  const listRef = React.useRef(null);
  // 住宿锚点（每天起点）不参与拖拽/删除，固定在列表最前
  const anchors = rawTimeline.filter(raw => raw.type === "hotel");
  const editable = rawTimeline
    .map((raw, index) => ({ raw, index }))
    .filter(entry => entry.raw.type !== "hotel");
  const offset = anchors.length;

  React.useEffect(() => {
    // CDN 加载失败时优雅降级：拖拽不可用，但更换/删除/改时间照常
    if (!listRef.current || !window.Sortable) return;
    const s = window.Sortable.create(listRef.current, {
      animation: 180,
      handle: ".drag-grip",
      ghostClass: "edit-ghost",
      onEnd: (evt) => {
        if (evt.oldIndex !== evt.newIndex) onReorder(evt.oldIndex + offset, evt.newIndex + offset);
      },
    });
    return () => s.destroy();
  // onReorder 不进依赖：每次变更后 ver 立即 +1 重建 Sortable，闭包不会失效
  }, [ver]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="ed-timeline">
      {anchors.map((raw, i) => (
        <div key={`${ver}-anchor-${i}`} className="ed-row">
          <div className="tl-time"></div>
          <div className="tl-rail"><span className="tl-dot"></span></div>
          <div className="ed-card is-anchor">
            <span className="flag">起点</span>
            <div className="ed-body">
              <div className="ed-title">{raw.name || "住宿"}</div>
              <div className="ed-meta">
                <span>每天从住宿出发，首站时间已含通勤</span>
                {raw.address && <span>{raw.address}</span>}
              </div>
            </div>
          </div>
        </div>
      ))}
      <div ref={listRef} key={ver} className="ed-list">
        {editable.map(({ raw, index }) => {
          const note = raw.dist_from_prev_km != null
            ? walkNote(raw.dist_from_prev_km)
            : "道路距离待核验";
          const isMeal = raw.type !== "attraction";
          return (
            <div key={`${ver}-${index}`} className="ed-row">
              {note && (
                <React.Fragment>
                  <div></div>
                  <div className="tl-rail"></div>
                  <div className="tl-walk"><WalkIcon />{note}</div>
                </React.Fragment>
              )}
              <div className="tl-time">{isMeal ? "" : (raw.start_time || "")}</div>
              <div className="tl-rail"><span className={`tl-dot${isMeal ? " is-meal" : ""}`}></span></div>
              <EditCard raw={raw}
                onReplace={() => onReplace(index)}
                onDelete={() => onDelete(index)}
                onTimeChange={(st, et) => onTimeChange(index, st, et)}
                onDropCandidate={raw.type === "attraction" && onDropCandidate ? (c) => onDropCandidate(index, c) : undefined} />
            </div>
          );
        })}
      </div>
      {editable.length === 0 && <div className="ed-empty">这一天还没有安排，用下面的按钮添加吧。</div>}

      <div className="ed-add-row">
        <button className="ed-add" onClick={() => onAdd("attraction")}>＋ 景点</button>
        <button className="ed-add" onClick={() => onAdd("lunch")}>＋ 午餐</button>
        <button className="ed-add" onClick={() => onAdd("dinner")}>＋ 晚餐</button>
      </div>
    </div>
  );
}

/* ── 编辑工具栏 ─────────────────────────────────────── */
function EditToolbar({ canUndo, canRedo, saving, saveErr, onUndo, onRedo, onCancel, onSave }) {
  return (
    <div className="ed-toolbar">
      <button className="ed-tool" disabled={!canUndo} onClick={onUndo}>↩ 撤销</button>
      <button className="ed-tool" disabled={!canRedo} onClick={onRedo}>↪ 重做</button>
      <span className="ed-hint">{saveErr ? "" : "拖动 ⠿ 调整顺序 · 点时间可修改"}</span>
      {saveErr && <span className="ed-err">{saveErr}</span>}
      <button className="ed-tool" onClick={onCancel}>✕ 取消</button>
      <button className="ed-tool is-primary" disabled={saving} onClick={onSave}>
        {saving ? "保存中…" : "✓ 完成编辑"}
      </button>
    </div>
  );
}

Object.assign(window, {
  recalcDayDists, reorderKeepTimes,
  PoiSearchModal, TimeRangeEditor, EditCard, EditableTimeline, EditToolbar,
});
