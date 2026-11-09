// pages.jsx — 四个页面 + 认证/顾虑模态框

// 后端节点 → 流程图阶段，用于展示当前规划所在的 Graph 节点。
const GRAPH_FLOW_STAGES = {
  intent:             "意图解析与约束提取",
  clarify:            "确认旅行信息",
  query_rewrite:      "查询改写 / 天气 / 餐馆候选",
  weather_search:     "查询改写 / 天气 / 餐馆候选",
  main_meal_search:   "查询改写 / 天气 / 餐馆候选",
  attraction_search:  "基础景点检索",
  candidate_react:    "候选校验 ⇄ 有界 ReAct 补查",
  candidate_search:   "候选校验 ⇄ 有界 ReAct 补查",
  candidate_validator:"候选校验 ⇄ 有界 ReAct 补查",
  candidate_ready:    "候选校验 ⇄ 有界 ReAct 补查",
  planner:            "联合 Planner",
  route_distance_check:"并发道路核验",
  risk_gate:          "规则门控",
  reviewer:           "Reviewer 评审",
  time_check:         "时间核查",
  snapshot_gate:      "记录硬约束与六维评分快照",
  snapshot_reviewer:  "记录硬约束与六维评分快照",
  snapshot_time_check:"记录硬约束与六维评分快照",
  meal_search:        "餐饮 / 贴士整理",
  meal_recommend:     "餐饮 / 贴士整理",
  meal_enrichment:    "餐饮 / 贴士整理",
  main_meal_output:   "餐饮 / 贴士整理",
  spot_tips:          "餐饮 / 贴士整理",
  finalize:           "Finalize · 历史择优与统一结果",
  finalize_direct:    "Finalize · 历史择优与统一结果",
};

// 首屏右侧「编排流水线」说明（与 JOURNEY_STEPS 同一套人类可读阶段）
const PIPELINE_NOTES = [
  "理解目的地、日期与偏好",
  "检索并校验景点候选池",
  "联合编排景点与餐厅",
  "评审返工与开放时间核查",
  "补充餐饮、贴士与预算",
  "落库归档并可随时微调",
];

/* ── 认证模态 ─────────────────────────────────────────── */
function AuthModal({ onSuccess, onClose, reason }) {
  const [tab, setTab] = React.useState("login");
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [err, setErr] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  const submit = async () => {
    if (!username.trim() || !password.trim()) { setErr("请填写用户名和密码"); return; }
    setLoading(true); setErr("");
    try {
      let res;
      if (tab === "login") {
        res = await loginApi(username.trim(), password);
      } else {
        res = await registerApi(username.trim(), password);
        if (!res.token) {
          // 注册成功但需要再登录
          res = await loginApi(username.trim(), password);
        }
      }
      setAuth(res.token, res.username || username.trim());
      onSuccess && onSuccess(res.username || username.trim());
    } catch (e) {
      setErr(e.message || "操作失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="tm-scrim" onClick={(e) => e.target === e.currentTarget && onClose && onClose()}>
      <div className="tm-sheet">
        <button className="tm-close" onClick={onClose} aria-label="关闭">✕</button>
        <div className="tm-sheet-title">途见</div>
        {reason && <div className="tm-sheet-sub">{reason}</div>}
        <div className="tm-tabs">
          <button className={`tm-tab ${tab === "login" ? "active" : ""}`} onClick={() => { setTab("login"); setErr(""); }}>登录</button>
          <button className={`tm-tab ${tab === "register" ? "active" : ""}`} onClick={() => { setTab("register"); setErr(""); }}>注册</button>
        </div>
        <label className="tm-field">
          <span className="tm-field-label">用户名</span>
          <input className="tm-input" value={username} onChange={e => setUsername(e.target.value)}
            placeholder="输入用户名" autoFocus
            onKeyDown={e => e.key === "Enter" && submit()} />
        </label>
        <label className="tm-field">
          <span className="tm-field-label">密码</span>
          <input className="tm-input" type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder="输入密码"
            onKeyDown={e => e.key === "Enter" && submit()} />
        </label>
        <div className="tm-error">{err}</div>
        <button className="tm-btn tm-btn--primary tm-submit" disabled={loading} onClick={submit}>
          {loading ? "处理中…" : tab === "login" ? "登录" : "注册并登录"}
        </button>
      </div>
    </div>
  );
}

/* ── 修改顾虑模态 ─────────────────────────────────────── */
function ConcernModal({ concern, onKeep, onConfirm }) {
  return (
    <div className="tm-scrim">
      <div className="tm-sheet">
        <div className="tm-sheet-title">规划师有个顾虑</div>
        <div className="tm-sheet-sub">AI 在调整行程时发现了一个问题，请你决定如何处理：</div>
        <div className="tm-concern">{concern}</div>
        <div className="tm-sheet-actions">
          <button className="tm-btn tm-btn--quiet" onClick={onKeep}>放弃，保留原行程</button>
          <button className="tm-btn tm-btn--primary" onClick={onConfirm}>确认，继续修改</button>
        </div>
      </div>
    </div>
  );
}

/* ── 主页（新建规划） ─────────────────────────────────── */
function PlanPage({ onRequestLogin, currentUsername, onPhaseChange, onPlanReady, modifyTrigger, onCancelModify, onManageProfile }) {
  const [phase, setPhase] = React.useState("idle");

  React.useEffect(() => { onPhaseChange?.(phase); }, [phase]); // eslint-disable-line
  const [query, setQuery] = React.useState("");
  const [planId, setPlanId] = React.useState(null);
  const [logs, setLogs] = React.useState([]);
  const [activeNode, setActiveNode] = React.useState(null);
  const [doneNodes, setDoneNodes] = React.useState([]);
  const [graphNodes, setGraphNodes] = React.useState([]);
  const [graphRound, setGraphRound] = React.useState(null);
  const [stageLabel, setStageLabel] = React.useState("");
  const [liveNarration, setLiveNarration] = React.useState("旅行助手已出发，正在整理你的需求…");
  const [stageReport, setStageReport] = React.useState("");
  const [stageReports, setStageReports] = React.useState({});
  const [missingFields, setMissingFields] = React.useState([]);
  const [supplementalStartDate, setSupplementalStartDate] = React.useState("");
  const [supplementalEndDate, setSupplementalEndDate] = React.useState("");
  const [dateValidationError, setDateValidationError] = React.useState("");
  const [threadId, setThreadId] = React.useState(null);
  const [concernModal, setConcernModal] = React.useState(null);
  const [pendingModState, setPendingModState] = React.useState(null);
  const [errMsg, setErrMsg] = React.useState("");
  const [elapsedSeconds, setElapsedSeconds] = React.useState(0);
  const [runId, setRunId] = React.useState(null);
  const [profile, setProfile] = React.useState(null);
  const abortRef = React.useRef(null);
  // 旅程已走到的最远站点下标：planner⇄reviewer / planner⇄time_check 循环时只前进不后退
  const maxStepRef = React.useRef(-1);
  const narrationIndexRef = React.useRef(0);
  const runningStagesRef = React.useRef({});
  const startDateRef = React.useRef(null);

  const hasDateMissing = missingFields.some(field => String(field).includes("日期"));

  React.useEffect(() => {
    if (!hasDateMissing) return;
    window.setTimeout(() => startDateRef.current?.focus(), 80);
  }, [hasDateMissing]);

  const narrationPool = (node) => ({
    intent: [
      "先对齐目的地、日期和游玩偏好，避免后面规划跑偏。",
      "正在检查出行日期是否完整，并尝试获取对应天气信息。",
    ],
    query_rewrite: [
      "正在结合你的历史偏好，把需求改写成更适合检索的表达。",
      "本次明确需求优先于历史偏好，正在处理可能的冲突。",
    ],
    attraction_search: [
      "正在搜索通用候选池，也会核验你明确提到的景点。",
      "候选景点会先检查名称、坐标和评分，避免把不存在的地点写进计划。",
    ],
    planner: [
      "规划师正在联合安排景点、餐厅和通勤时间。",
      "正在检查游览和用餐时段，并尽量减少跨区折返。",
    ],
    reviewer: [
      "评审 Agent 正在检查路线是否使用了候选池外的景点，以及是否满足你的约束。",
      "如果发现问题，会把明确的返工意见交回规划 Agent。",
    ],
    time_check: [
      "正在核对景点开放时间和安排时段，避免到了才发现闭馆。",
      "时间冲突会触发局部返工，不会直接丢掉整份行程。",
    ],
    meal_search: [
      "正在围绕当天路线搜索附近餐厅，减少吃饭时来回绕路。",
      "正在根据景点坐标确定午餐和晚餐的搜索范围。",
    ],
    meal_recommend: [
      "正在从附近候选餐厅中挑选午餐和晚餐，并参考你的口味偏好。",
      "餐厅信息不足时会保留提示，不会编造店铺。",
    ],
    spot_tips: [
      "正在为行程中的景点补充游玩贴士和天气提醒。",
      "最后检查一次信息是否齐全，马上为你整理成可读的行程单。",
    ],
    finalize: [
      "正在收进行程、路线距离和注意事项，马上就能出发了。",
    ],
  })[node] || ["多个 Agent 正在交接结果，请稍等片刻。"];

  const updateNarration = (node) => {
    const pool = narrationPool(node);
    const index = narrationIndexRef.current++ % pool.length;
    setLiveNarration(pool[index]);
  };

  React.useEffect(() => () => abortRef.current && abortRef.current(), []);

  React.useEffect(() => {
    if (phase !== "loading") return;
    const startedAt = Date.now();
    setElapsedSeconds(0);
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [phase]);

  // 拉取用户画像，在新建规划页展示，引导用户参考自身偏好斟酌措辞
  // 依赖 currentUsername：用户登录后立即刷新展示，登出则清空（无需重新进入本页）
  React.useEffect(() => {
    if (!getAuth()) { setProfile(null); return; }
    getProfile().then(setProfile).catch(() => {});
  }, [currentUsername]);

  // 由 App 传入修改触发器，在挂载时（planKey bump 后）立即执行修改流
  React.useEffect(() => {
    if (modifyTrigger) {
      doStream({
        query: modifyTrigger.query,
        plan_id: modifyTrigger.planId,
        modification_notes: modifyTrigger.query,
        selected_poi_name: modifyTrigger.selectedPoiName || undefined,
      });
    }
  }, []); // eslint-disable-line

  const handleStage = (ev) => {
    runningStagesRef.current[ev.node] = ev.label || ev.node;
    setLogs(prev => [...prev, ev.label || ev.node]);
    setStageLabel(Object.values(runningStagesRef.current).join(" · "));
    setGraphNodes(prev => prev[prev.length - 1] === ev.node ? prev : [...prev, ev.node]);
    if (ev.round) setGraphRound(ev.round);
    updateNarration(ev.node);
    const key = NODE_TO_STEP[ev.node] || ev.node;
    const idx = JOURNEY_STEPS.findIndex(s => s.key === key);
    if (idx < 0 || idx <= maxStepRef.current) return; // 未知节点或回头路（多轮循环）不动刻度
    maxStepRef.current = idx;
    setActiveNode(key);
    setDoneNodes(JOURNEY_STEPS.slice(0, idx).map(s => s.key));
  };

  const resetJourney = () => {
    runningStagesRef.current = {};
    maxStepRef.current = -1;
    setActiveNode(null);
    setDoneNodes([]);
    setGraphNodes([]);
    setGraphRound(null);
    setStageLabel("");
    narrationIndexRef.current = 0;
    setLiveNarration("旅行助手已出发，正在整理你的需求…");
    setStageReport("");
    setStageReports({});
  };

  const completeStage = (ev) => {
    delete runningStagesRef.current[ev.node];
    const labels = Object.values(runningStagesRef.current);
    setStageLabel(labels.join(" · "));
    setLiveNarration(labels.length ? labels.join(" · ") : ev.summary);
  };

  React.useEffect(() => {
    if (phase !== "loading") return;
    const timer = window.setInterval(() => updateNarration(activeNode || "intent"), 3600);
    return () => window.clearInterval(timer);
  }, [phase, activeNode]); // eslint-disable-line

  const onStageSummary = (ev) => {
    if (!ev.summary) return;
    completeStage(ev);
    setStageReport(ev.summary);
    const step = NODE_TO_STEP[ev.node] || ev.node;
    setStageReports(prev => ({
      ...prev,
      [step]: prev[step] ? `${prev[step]} → ${ev.summary}` : ev.summary,
    }));
    setLogs(prev => [...prev, `✓ ${ev.summary}`]);
  };

  const doStream = (body) => {
    setPhase("loading");
    const isModify = !!(body.plan_id && body.modification_notes);
    if (isModify) {
      runningStagesRef.current = {};
      const preDone = JOURNEY_STEPS.slice(0, 3).map(s => s.key);
      maxStepRef.current = 3;
      setDoneNodes(preDone);
      setActiveNode("plan_review");
      setGraphNodes([]);
      setGraphRound(null);
      setStageLabel("");
      setLogs([]);
      setStageReports({});
    } else {
      resetJourney();
    }
    setErrMsg("");
    setRunId(null);

    streamPlan(body, {
      onAbort: (fn) => { abortRef.current = fn; },
      onRun: (ev) => setRunId(ev.run_id || null),
      onStage: handleStage,
      onStageSummary,
      onResult: (ev) => {
        const adapted = adaptPlan(ev.plan, currentUsername);
        adapted.logs = ev.history || logs;
        setPlanId(ev.plan_id);
        setDoneNodes(JOURNEY_STEPS.map(s => s.key));
        setTimeout(() => { onPlanReady?.(adapted, ev.plan_id); setPhase("idle"); }, 600);
      },
      onMissingFields: (ev) => {
        setMissingFields(ev.missing_fields || []);
        setThreadId(ev.thread_id || null);
        setPhase("idle");
      },
      onWarning: (ev) => {
        setConcernModal({
          concern: ev.concern,
          pending_id: ev.pending_id,
          parent_plan_id: ev.parent_plan_id || planId,
        });
        setPhase("idle");
      },
      onError: (msg) => {
        setErrMsg(msg);
        setPhase("idle");
      },
    });
  };

  const startPlan = () => {
    if (!getAuth()) { onRequestLogin && onRequestLogin(); return; }
    const q = threadId ? (query + " " + (threadId || "")).trim() : query.trim();
    if (!q) return;
    setMissingFields([]);
    doStream({ query: q, thread_id: threadId || undefined });
  };

  const continueWithDates = () => {
    if (!supplementalStartDate || !supplementalEndDate) {
      setDateValidationError("请同时选择开始日期和结束日期");
      return;
    }
    if (supplementalEndDate < supplementalStartDate) {
      setDateValidationError("结束日期不能早于开始日期");
      return;
    }
    const enrichedQuery = `${query.trim()}，出行日期为 ${supplementalStartDate} 至 ${supplementalEndDate}`;
    setQuery(enrichedQuery);
    setDateValidationError("");
    setMissingFields([]);
    doStream({ query: enrichedQuery, thread_id: threadId || undefined });
  };

  const confirmConcern = async () => {
    const { pending_id, parent_plan_id } = concernModal;
    setConcernModal(null);
    setPhase("loading");
    resetJourney();
    confirmModification(pending_id, parent_plan_id, {
      onAbort: (fn) => { abortRef.current = fn; },
      onRun: (ev) => setRunId(ev.run_id || null),
      onStage: handleStage,
      onStageSummary,
      onResult: (ev) => {
        const adapted = adaptPlan(ev.plan, currentUsername);
        const newPlanId = ev.plan_id || planId;
        setPlanId(newPlanId);
        setDoneNodes(JOURNEY_STEPS.map(s => s.key));
        setTimeout(() => { onPlanReady?.(adapted, newPlanId); setPhase("idle"); }, 600);
      },
      onError: (msg) => { setErrMsg(msg); setPhase("idle"); },
    });
  };

  const examples = [
    "北京明天三日游，想玩颐和园、故宫，不喜欢走太多路",
    "成都周末两天，想泡茶馆吃火锅",
    "杭州一日，西湖边慢慢走",
  ];

  // 画像偏好行（仅渲染非空字段；全空则整块隐藏）
  const profileRows = profile ? [
    { key: "attr", label: "景点", items: profile.attraction_prefs || [] },
    { key: "food", label: "餐饮", items: profile.food_prefs || [] },
    { key: "habit", label: "习惯", items: profile.habit_prefs || [] },
  ].filter(r => r.items.length) : [];

  // ── 规划中：运行监控 ──
  const graphLastNode = graphNodes[graphNodes.length - 1] || "";
  const graphStage = GRAPH_FLOW_STAGES[graphLastNode] || "";
  if (phase === "loading") {
    return (
      <div className="tm-page run">
        <div className="run-head">
          <div className="run-head-main">
            <div className="tm-eyebrow">Agent Pipeline · Running</div>
            <h2 className="run-title">正在编排这趟旅程</h2>
          </div>
          <div className="run-timer">
            <b>{elapsedSeconds}</b>
            <small>sec</small>
          </div>
          <button
            type="button"
            className="tm-btn tm-btn--quiet tm-btn--sm"
            title="取消本次规划"
            onClick={() => {
              abortRef.current && abortRef.current();
              setErrMsg("已取消本次规划");
              setPhase("idle");
            }}
          >取消</button>
        </div>

        <div className="run-graph" aria-live="polite">
          <span className="run-graph-label">Graph</span>
          {graphNodes.length === 0 ? (
            <span className="run-graph-stage">等待节点启动</span>
          ) : graphNodes.slice(-6).map((node, idx, list) => (
            <React.Fragment key={`${node}-${graphNodes.length - list.length + idx}`}>
              {idx > 0 && <span className="run-arrow">›</span>}
              <span className={`run-node${idx === list.length - 1 ? " is-active" : ""}`} title={GRAPH_FLOW_STAGES[node] || node}>
                {node}
              </span>
            </React.Fragment>
          ))}
          <span className="run-graph-meta">
            {runId ? <span className="run-round">{runId.slice(0, 8)}</span> : null}
            {graphRound ? <span className="run-round">第 {graphRound} 轮</span> : null}
            {graphStage && <span className="run-graph-stage">{graphStage}</span>}
          </span>
        </div>

        <JourneyLoading steps={JOURNEY_STEPS} activeNode={activeNode} doneNodes={doneNodes} />

        <div className="run-live" aria-live="polite">
          <span className="run-live-dot"></span>
          <span className="run-live-title">播报</span>
          <span>{liveNarration}</span>
          {elapsedSeconds >= 30 && (
            <span className="run-slow">当前阶段响应较慢，超时后会自动结束。</span>
          )}
        </div>

        {stageReport && (
          <div className="run-quote" aria-live="polite">
            <span>✓</span>
            <span>{stageReport}</span>
          </div>
        )}

        <div className="run-steps">
          {JOURNEY_STEPS.map((s, i) => {
            const isDone = doneNodes.includes(s.key);
            const isActive = s.key === activeNode;
            return (
              <div key={s.key} className={`run-step${isDone ? " done" : isActive ? " active" : ""}`}>
                <span className="run-step-num">{isDone ? "✓" : String(i + 1).padStart(2, "0")}</span>
                <span className="run-step-label">{s.label}</span>
                <span className="run-step-detail" title={stageReports[s.key] || s.detail}>
                  {stageReports[s.key] || (isActive && stageLabel ? stageLabel : s.detail)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // ── 首屏 ──
  return (
    <div className="tm-page">
      {concernModal && (
        <ConcernModal
          concern={concernModal.concern}
          onKeep={() => { setConcernModal(null); onCancelModify?.(); }}
          onConfirm={confirmConcern}
        />
      )}

      <div className="pl-masthead">
        <div className="tm-eyebrow">TravelMind — 多 Agent 行程编排</div>
        <h1 className="pl-title">把目的地交给我，<br />你只管<em>期待出发</em>。</h1>
        <p className="pl-lede">
          告诉我想去哪里、哪几天、喜欢什么——多位 Agent 会查景点、核路线、看天气、找馆子，
          几分钟内排出一份可以直接照着走的行程。
        </p>
      </div>

      <div className="pl-grid">
        <div className="pl-brief">
          <div className="pl-brief-label">描述你的旅行需求（目的地、日期、偏好）</div>
          <textarea
            className="pl-textarea"
            placeholder="例如：北京明天三日游，想玩颐和园、故宫，不喜欢走太多路"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) startPlan(); }}
          />

          {missingFields.length > 0 && (
            <div className="pl-alert" role="alert" aria-live="assertive">
              <strong>{hasDateMissing ? "还差出行日期，暂时不能开始规划" : "旅行信息还不完整"}</strong>
              <p>
                {hasDateMissing
                  ? "请在下方补充开始和结束日期，系统会接着刚才的需求继续规划。"
                  : `请在上面的需求描述中补充：${missingFields.join("、")}。`}
              </p>
              <div className="pl-missing">
                {missingFields.map(f => <span key={f} className="flag flag--accent">缺少 · {f}</span>)}
              </div>
              {hasDateMissing && (
                <div className="pl-dates">
                  <label className="pl-date">
                    <span>开始日期</span>
                    <input
                      ref={startDateRef}
                      type="date"
                      value={supplementalStartDate}
                      onChange={e => { setSupplementalStartDate(e.target.value); setDateValidationError(""); }}
                    />
                  </label>
                  <span className="run-arrow" aria-hidden="true">→</span>
                  <label className="pl-date">
                    <span>结束日期</span>
                    <input
                      type="date"
                      min={supplementalStartDate || undefined}
                      value={supplementalEndDate}
                      onChange={e => { setSupplementalEndDate(e.target.value); setDateValidationError(""); }}
                    />
                  </label>
                  <button className="tm-btn tm-btn--primary tm-btn--sm" onClick={continueWithDates}>
                    补充日期并继续 <span>→</span>
                  </button>
                </div>
              )}
              {dateValidationError && <div className="pl-error">⚠ {dateValidationError}</div>}
            </div>
          )}

          {errMsg && <div className="pl-inline-err">{errMsg}</div>}

          <div className="pl-foot">
            <div className="pl-examples">
              {examples.map((ex) => (
                <button key={ex} className="pl-example" onClick={() => setQuery(ex)}>{ex.slice(0, 14)}…</button>
              ))}
            </div>
            <button
              className="tm-btn tm-btn--primary pl-cta"
              onClick={startPlan}
              disabled={!query.trim() || hasDateMissing}
            >
              {hasDateMissing ? "请先补充日期" : missingFields.length > 0 ? "提交补充信息" : "开始规划"} <span>→</span>
            </button>
          </div>
        </div>

        <aside className="pl-aside">
          {profileRows.length > 0 && (
            <div className="pl-aside-block">
              <div className="pl-aside-title">
                <span>我记住的你</span>
                <button onClick={onManageProfile}>管理画像</button>
              </div>
              <p className="pl-aside-note">
                这些偏好来自你过往的行程记录。规划时说得越贴合，行程越懂你。
              </p>
              {profileRows.map(r => (
                <div key={r.key} className="pl-chiprow">
                  <span className="pl-chiplabel">{r.label}</span>
                  <div className="pl-chips">
                    {r.items.map((it, i) => <span key={i} className="pl-chip">{it}</span>)}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="pl-aside-block">
            <div className="pl-aside-title"><span>编排流水线</span></div>
            <div className="run-steps" style={{ marginTop: 0, borderTop: 0 }}>
              {PIPELINE_NOTES.map((note, i) => (
                <div className="run-step" key={note} style={{ gridTemplateColumns: "32px minmax(0,1fr)", padding: "10px 0" }}>
                  <span className="run-step-num">{String(i + 1).padStart(2, "0")}</span>
                  <span className="run-step-label" style={{ color: "var(--ink-2)" }}>{note}</span>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

/* ── 行程详情页 ───────────────────────────────────────── */
function TripDetailPage({ plan: planProp, planId: planIdProp, onRequestModify, onRequestLogin, currentUsername }) {
  const [plan, setPlan] = React.useState(planProp);
  const [planId, setPlanId] = React.useState(planIdProp);
  const [dayIdx, setDayIdx] = React.useState(0);
  const [modQuery, setModQuery] = React.useState("");
  const [optimizedDays, setOptimizedDays] = React.useState({});
  const [optimizingDay, setOptimizingDay] = React.useState(null);
  const [dayMsg, setDayMsg] = React.useState(null);
  const [hotel, setHotel] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const [metaDirty, setMetaDirty] = React.useState(false);
  const [metaSaving, setMetaSaving] = React.useState(false);
  const [activeNavKey, setActiveNavKey] = React.useState(null);
  const [activeNavPair, setActiveNavPair] = React.useState(null);
  const [nearbyTarget, setNearbyTarget] = React.useState(null);
  const [themeInput, setThemeInput] = React.useState("");
  const [livePriceStatus, setLivePriceStatus] = React.useState("idle");

  React.useEffect(() => {
    // 详情页一旦拥有已保存行程的 ID，就后台实时核验价格。
    // 不依赖页面跳转时附带的标记，避免历史卡片/直链场景漏掉刷新。
    if (!planIdProp) return;
    const controller = new AbortController();
    let alive = true;
    setLivePriceStatus("loading");
    getHistoryItemLivePrices(planIdProp, controller.signal)
      .then(data => {
        if (!alive || !data?.plan) return;
        const adapted = adaptPlan(data.plan, currentUsername);
        adapted.logs = data.plan.history || planProp.logs || [];
        setPlan(adapted);
        setLivePriceStatus("done");
        window.setTimeout(() => { if (alive) setLivePriceStatus("idle"); }, 5000);
      })
      .catch(error => {
        if (alive && error?.name !== "AbortError") setLivePriceStatus("failed");
      });
    return () => { alive = false; controller.abort(); };
  }, [planIdProp, planProp?._raw?.__refresh_live_prices, currentUsername]); // eslint-disable-line

  React.useEffect(() => {
    setPlan(planProp);
    setPlanId(planIdProp);
    setDayIdx(0);
    setModQuery("");
    setOptimizedDays({});
    setOptimizingDay(null);
    setDayMsg(null);
    setHotel(planProp?.hotel || "");
    setNotes(planProp?.notes || "");
    setMetaDirty(false);
    setActiveNavKey(null);
    setActiveNavPair(null);
    setNearbyTarget(null);
    // 切换行程时清除编辑态，防止残留
    setEditing(false);
    setDraft(null); draftRef.current = null;
    setUndoStack([]);
    setRedoStack([]);
    setSaveErr("");
    setSearchTarget(null);
    setReplanSearchOpen(false);
  }, [planProp, planIdProp]);

  const applyDayTimeline = (dayI, timeline) => {
    const raw = { ...plan._raw, days: plan._raw.days.map((d, i) => i === dayI ? { ...d, timeline } : d) };
    const adapted = adaptPlan(raw, currentUsername);
    adapted.logs = plan.logs;
    setPlan(adapted);
  };

  const showDayMsg = (dayNo, text) => {
    setDayMsg({ day: dayNo, text });
    setTimeout(() => setDayMsg(m => (m && m.day === dayNo && m.text === text ? null : m)), 5000);
  };

  const handleOptimize = async (dayNo) => {
    if (!confirm("将按最短路程优化景点游玩顺序，餐厅需要你重新规划")) return;
    setOptimizingDay(dayNo);
    try {
      const dayI = dayNo - 1;
      const rawTimeline = plan._raw?.days?.[dayI]?.timeline;
      const res = await optimizeDay(planId, dayNo);
      if (res.optimized_day) {
        if (res.improved) {
          setOptimizedDays(prev => ({ ...prev, [dayI]: rawTimeline }));
          showDayMsg(dayNo, `已优化：${res.original_km}km → ${res.optimized_km}km`);
        } else {
          showDayMsg(dayNo, "当前顺序已是最短路线");
        }
        applyDayTimeline(dayI, res.optimized_day.timeline);
      }
    } catch (e) { alert(e.message || "优化失败"); }
    finally { setOptimizingDay(null); }
  };

  const handleNav = (key, pair, nearbyItem) => {
    if (nearbyItem) {
      setNearbyTarget({ location: nearbyItem.location, name: nearbyItem.name });
      return;
    }
    if (key === activeNavKey) {
      setActiveNavKey(null); setActiveNavPair(null);
    } else {
      setActiveNavKey(key); setActiveNavPair(pair);
    }
  };

  const handleSaveMeta = async () => {
    setMetaSaving(true);
    try {
      await savePlanMetadata(planId, { hotel, notes });
      setMetaDirty(false);
    } catch (e) { alert(e.message || "保存失败"); }
    finally { setMetaSaving(false); }
  };

  const handleRevert = async (dayNo) => {
    const dayI = dayNo - 1;
    const orig = optimizedDays[dayI];
    if (!orig || !planId) return;
    try {
      await revertDay(planId, dayNo, orig);
      setOptimizedDays(prev => { const n = { ...prev }; delete n[dayI]; return n; });
      applyDayTimeline(dayI, orig);
      showDayMsg(dayNo, "已回退到优化前的顺序");
    } catch (e) { alert(e.message || "回退失败"); }
  };

  // ── 手动编辑态 ──
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(null);          // _raw.days 的深拷贝
  const draftRef = React.useRef(null);
  React.useEffect(() => { draftRef.current = draft; }, [draft]);
  const [undoStack, setUndoStack] = React.useState([]);    // 元素 = draft 快照
  const [redoStack, setRedoStack] = React.useState([]);
  const [editVer, setEditVer] = React.useState(0);         // 每次变更 +1，驱动 Sortable 重挂载
  const [saving, setSaving] = React.useState(false);
  const [saveErr, setSaveErr] = React.useState("");
  // 搜索弹层目标：{ dayI, idx } 替换；{ dayI, idx:null, addType } 新增
  const [searchTarget, setSearchTarget] = React.useState(null);
  const [replanSearchOpen, setReplanSearchOpen] = React.useState(false);

  const dirty = undoStack.length > 0;
  const dirtyRef = React.useRef(false);
  React.useEffect(() => { dirtyRef.current = dirty; }, [dirty]);

  // 编辑中刷新/关页守卫（dirtyRef 避免 beforeunload 闭包捕获过期 dirty 值）
  React.useEffect(() => {
    if (!editing) return;
    const guard = (e) => { if (dirtyRef.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [editing]);

  const enterEdit = () => {
    const clone = structuredClone(plan._raw.days);
    setDraft(clone); draftRef.current = clone;
    setUndoStack([]); setRedoStack([]); setSaveErr("");
    setEditing(true); setEditVer(v => v + 1);
  };

  const exitEdit = () => {
    if (dirty && !confirm("放弃未保存的修改？")) return;
    setEditing(false); setDraft(null); draftRef.current = null; setSaveErr(""); setSearchTarget(null);
  };

  // 所有编辑操作的唯一入口：拷贝 → 变更 → 重算距离 → 压撤销栈
  // 经 draftRef 读最新值，同一 tick 多次调用也不会丢快照
  const applyEdit = (mutate) => {
    const cur = draftRef.current;
    setUndoStack(s => [...s, cur]);
    setRedoStack([]);
    const next = structuredClone(cur);
    mutate(next);
    next.forEach(d => recalcDayDists(d.timeline));
    setDraft(next);
    draftRef.current = next;
    setEditVer(v => v + 1);
  };

  const undo = () => {
    if (!undoStack.length) return;
    const cur = draftRef.current;
    const prev = undoStack[undoStack.length - 1];
    setRedoStack(r => [...r, cur]);
    setUndoStack(s => s.slice(0, -1));
    setDraft(prev);
    draftRef.current = prev;
    setEditVer(v => v + 1);
  };

  const redo = () => {
    if (!redoStack.length) return;
    const cur = draftRef.current;
    const next = redoStack[redoStack.length - 1];
    setUndoStack(s => [...s, cur]);
    setRedoStack(r => r.slice(0, -1));
    setDraft(next);
    draftRef.current = next;
    setEditVer(v => v + 1);
  };

  const saveEdit = async () => {
    setSaving(true); setSaveErr("");
    try {
      const days = draftRef.current.map((d, i) => ({ day: d.day ?? i + 1, timeline: d.timeline }));
      const res = await saveTimeline(planId, days);
      // 保存主题编辑
      const day_themes = {};
      draftRef.current.forEach((d, i) => { if (d.theme) day_themes[String(d.day ?? i + 1)] = d.theme; });
      if (Object.keys(day_themes).length) {
        try { await savePlanMetadata(planId, { day_themes }); } catch {}
      }
      const adapted = adaptPlan(res.plan, currentUsername);
      adapted.logs = plan.logs;
      setPlan(adapted);
      setEditing(false); setDraft(null); draftRef.current = null; setSearchTarget(null);
      setOptimizedDays({});   // 手动编辑后旧的"优化前快照"失效
    } catch (e) {
      // 网络层错误（Failed to fetch 等）对用户不可读，换成中文提示
      const msg = e.message && !/fetch|network/i.test(e.message) ? e.message : "保存失败，请检查网络后重试";
      setSaveErr(msg);
    } finally { setSaving(false); }
  };

  // ── 各编辑操作 ──
  const handleReorder = (from, to) =>
    applyEdit(d => { d[dayIdx].timeline = reorderKeepTimes(d[dayIdx].timeline, from, to); });

  const handleDelete = (idx) =>
    applyEdit(d => { d[dayIdx].timeline.splice(idx, 1); });

  const handleTimeChange = (idx, st, et) =>
    applyEdit(d => { Object.assign(d[dayIdx].timeline[idx], { start_time: st, end_time: et }); });

  const handlePoiPick = (poi) => {
    const { dayI, idx, addType } = searchTarget;
    setSearchTarget(null);
    applyEdit(d => {
      const tl = d[dayI].timeline;
      if (idx != null) {
        const old = tl[idx];
        if (old.type === "attraction") {
          // 继承时间段与时段，其余字段来自新 POI；旧贴士不再适用
          tl[idx] = { ...old, name: poi.name, rating: poi.rating ?? null,
            open_time: poi.open_time ?? null, location: poi.location,
            photo: poi.photo ?? null, tip: null };
        } else {
          tl[idx] = { type: old.type, name: poi.name, rating: poi.rating ?? null,
            cost: poi.cost ?? null, address: poi.address ?? null,
            location: poi.location, photo: poi.photo ?? null,
            reason: null, no_restaurant: false };
        }
      } else if (addType === "attraction") {
        tl.push({ type: "attraction", name: poi.name, rating: poi.rating ?? null,
          open_time: poi.open_time ?? null, location: poi.location,
          photo: poi.photo ?? null, tip: null,
          start_time: null, end_time: null, period: "afternoon" });
      } else {
        tl.push({ type: addType, name: poi.name, rating: poi.rating ?? null,
          cost: poi.cost ?? null, address: poi.address ?? null,
          location: poi.location, photo: poi.photo ?? null,
          reason: null, no_restaurant: false });
      }
    });
  };

  // 编辑态主题 input 同步
  React.useEffect(() => {
    if (editing && draft) setThemeInput(draft[dayIdx]?.theme || "");
  }, [editing, dayIdx, editVer]); // eslint-disable-line

  // 编辑态视图：draft 经 adaptPlan 渲染（地图点位/items 跟随编辑实时刷新）
  const editedView = React.useMemo(() => {
    if (!editing || !draft) return null;
    const adapted = adaptPlan({ ...plan._raw, days: draft }, currentUsername);
    adapted.logs = plan.logs;
    return adapted;
  }, [editing, editVer]); // editVer 是版本令牌：draft 每次变更都 +1，故意省略 draft/plan 直接依赖

  const startModify = () => {
    if (editing) {
      if (!confirm("正在手动编辑，离开将丢弃未保存的修改。继续？")) return;
      setEditing(false); setDraft(null); draftRef.current = null; setSaveErr("");
    }
    if (!getAuth()) { onRequestLogin?.(); return; }
    if (!modQuery.trim() || !planId) return;
    onRequestModify?.(modQuery, planId);
  };

  const handleReplanPoiPick = (poi) => {
    setReplanSearchOpen(false);
    if (!planId || !poi?.name) return;
    const message = `将“${poi.name}”加入行程，并重新安排景点顺序、游玩时间和周边餐饮。`;
    if (!confirm(`将核验“${poi.name}”并加入候选池，再重新生成整份行程。是否继续？`)) return;
    onRequestModify?.(message, planId, poi.name);
  };

  if (!plan) return null;
  const viewPlan = editing && editedView ? editedView : plan;
  const day = viewPlan.days[dayIdx];
  const dayNo = dayIdx + 1;
  const hasAttractions = (day.items || []).filter(it => it.type === "attraction").length >= 2;
  const isOptimized = optimizedDays[dayIdx] !== undefined;

  const handlePickMeal = async (poi, mealType) => {
    if (!planId) return;
    setNearbyTarget(null);
    const rawTimeline = plan._raw.days[dayIdx]?.timeline || [];
    const mealEntry = {
      type: mealType,
      name: poi.name,
      rating: poi.rating ?? null,
      cost: poi.cost ?? null,
      address: poi.address ?? null,
      location: poi.location ?? null,
      photo: poi.photo ?? null,
      open_time: poi.open_time ?? null,
      tel: poi.tel ?? null,
      reason: null,
      no_restaurant: false,
    };
    const hasSlot = rawTimeline.some(it => it.type === mealType);
    const newTimeline = hasSlot
      ? rawTimeline.map(item => item.type !== mealType ? item : mealEntry)
      : [...rawTimeline, mealEntry];
    try {
      await saveTimeline(planId, [{ day: dayIdx + 1, timeline: newTimeline }]);
      applyDayTimeline(dayIdx, newTimeline);
      showDayMsg(dayNo, `已更新${mealType === "lunch" ? "午餐" : "晚餐"}：${poi.name}`);
    } catch (e) {
      alert(e.message || "更新失败");
    }
  };

  return (
    <React.Fragment>
      {searchTarget && (
        <PoiSearchModal
          city={plan.destination}
          kind={searchTarget.idx != null
            ? (draft[searchTarget.dayI].timeline[searchTarget.idx].type === "attraction" ? "attraction" : "restaurant")
            : (searchTarget.addType === "attraction" ? "attraction" : "restaurant")}
          title={searchTarget.idx != null ? "更换为…" : "添加…"}
          onPick={handlePoiPick}
          onClose={() => setSearchTarget(null)} />
      )}
      {replanSearchOpen && (
        <PoiSearchModal
          city={plan.destination}
          kind="attraction"
          title="搜索景点并重新规划"
          onPick={handleReplanPoiPick}
          onClose={() => setReplanSearchOpen(false)} />
      )}
      {nearbyTarget && (
        <NearbySearchModal
          location={nearbyTarget.location}
          name={nearbyTarget.name}
          onClose={() => setNearbyTarget(null)}
          onPickMeal={handlePickMeal} />
      )}

      <div className="tm-page trip">
        {livePriceStatus !== "idle" && (
          <div className={`trip-live is-${livePriceStatus}`} role="status" aria-live="polite">
            <span className="trip-live-dot"></span>
            <strong>
              {livePriceStatus === "loading" && "行程已打开，正在后台实时核验门票与餐饮价格…"}
              {livePriceStatus === "done" && "实时价格已更新，预算已重新计算"}
              {livePriceStatus === "failed" && "实时价格暂时查询失败，行程内容仍可正常查看"}
            </strong>
          </div>
        )}

        <div className="trip-cover" key={planId || "new"}>
          <div className="trip-cover-img" style={{ backgroundImage: `url('${plan.cover_img}')` }}></div>
          <div className="trip-cover-veil"></div>
          <div className="trip-cover-body">
            <div className="tm-eyebrow">Itinerary · 行程总览</div>
            <h2 className="trip-title">{plan.title}</h2>
            <div className="trip-meta">
              <span>{plan.date_range}</span>
              {plan.budget_summary && (
                <span>预计 ¥{Number(plan.budget_summary.estimated_subtotal ?? plan.budget_summary.known_subtotal ?? 0).toFixed(0)}/人</span>
              )}
              {plan.badges.map((b) => <span key={b} className="trip-badge">{b}</span>)}
            </div>
          </div>
        </div>

        <div className="trip-subbar">
          <div className="trip-days">
            {plan.days.map((d, i) => (
              <button key={i} className={`trip-day${i === dayIdx ? " active" : ""}`}
                onClick={() => { setDayIdx(i); setActiveNavKey(null); setActiveNavPair(null); }}>
                <span>Day {i + 1}</span>
                <span className="trip-day-date">{d.date}</span>
              </button>
            ))}
          </div>

          {editing ? (
            <input
              className="trip-dayinput"
              value={themeInput}
              onChange={e => setThemeInput(e.target.value)}
              onBlur={() => {
                const cur = draft[dayIdx]?.theme || "";
                if (themeInput !== cur) applyEdit(d => { d[dayIdx].theme = themeInput; });
              }}
              onKeyDown={e => e.key === "Enter" && e.target.blur()}
            />
          ) : (
            <div className="trip-daytheme">{day.theme}</div>
          )}

          {dayMsg && dayMsg.day === dayNo && <span className="trip-msg">{dayMsg.text}</span>}

          <div className="trip-actions">
            {!editing && planId && (
              <button className="tm-btn tm-btn--quiet tm-btn--sm" onClick={enterEdit}>编辑行程</button>
            )}
            {!editing && planId && (
              <button className="tm-btn tm-btn--quiet tm-btn--sm" onClick={() => setReplanSearchOpen(true)}>＋ 添加景点</button>
            )}
            {!editing && hasAttractions && planId && (
              isOptimized ? (
                <button className="tm-btn tm-btn--quiet tm-btn--sm" onClick={() => handleRevert(dayNo)}>↩ 回退顺序</button>
              ) : (
                <button className="tm-btn tm-btn--quiet tm-btn--sm" disabled={optimizingDay === dayNo} onClick={() => handleOptimize(dayNo)}>
                  {optimizingDay === dayNo ? "优化中…" : "↔ 优化路线"}
                </button>
              )
            )}
          </div>
        </div>

        {plan.weather.length > 0 && (
          <div className="trip-weather">
            {plan.weather.map((w, i) => (
              <div key={i} className="trip-wcell">
                <span className="trip-wico">{w.icon}</span>
                <div>
                  <div className="trip-wday">{w.day}</div>
                  <div className="trip-wtemp">
                    <span>{w.text}</span>
                    <b>{w.hi}°</b>
                    <span className="trip-wsep">/</span>
                    <span>{w.lo}°</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="trip-grid">
          <div className="trip-main">
            <RecommendStrip candidates={viewPlan.candidate_spots} editing={editing} />

            {!editing && <DayBudget budget={day.budget} mobilityAdvice={day.mobility_advice} />}

            {!editing && plan.hotel_info && dayIdx === 0 && (
              <div className="mobility-note">
                住宿预算：{plan.hotel_info.nightly_price != null
                  ? `约 ¥${Number(plan.hotel_info.nightly_price).toFixed(0)}/间夜 × ${plan.hotel_info.nights} 晚 = ¥${Number(plan.hotel_info.estimated_total).toFixed(0)}`
                  : "本次高德未返回可用房价"}（按房间计，不混入人均日预算）
              </div>
            )}

            {editing ? (
              <React.Fragment>
                <EditToolbar canUndo={undoStack.length > 0} canRedo={redoStack.length > 0}
                  saving={saving} saveErr={saveErr}
                  onUndo={undo} onRedo={redo} onCancel={exitEdit} onSave={saveEdit} />
                <EditableTimeline rawTimeline={draft[dayIdx].timeline} ver={`${dayIdx}-${editVer}`}
                  onReorder={handleReorder}
                  onReplace={(idx) => setSearchTarget({ dayI: dayIdx, idx })}
                  onDelete={handleDelete}
                  onTimeChange={handleTimeChange}
                  onAdd={(addType) => setSearchTarget({ dayI: dayIdx, idx: null, addType })}
                  onDropCandidate={(idx, candidate) => {
                    applyEdit(d => {
                      const old = d[dayIdx].timeline[idx];
                      d[dayIdx].timeline[idx] = {
                        ...old,
                        name: candidate.name,
                        rating: candidate.rating ?? null,
                        open_time: candidate.open_time ?? null,
                        location: candidate.location,
                        photo: candidate.photo ?? null,
                        address: candidate.address ?? null,
                        tip: null,
                      };
                    });
                  }} />
              </React.Fragment>
            ) : (
              <Timeline items={day.items} city={plan.destination} key={dayIdx} onNav={handleNav} activeNavKey={activeNavKey} />
            )}

            <div className="trip-note">
              <div className="trip-note-title">编辑手记</div>
              {plan.tips.length > 0 ? (
                <ul className="trip-note-list">{plan.tips.map((t, i) => <li key={i}>{t}</li>)}</ul>
              ) : (
                <div className="trip-note-text">行程已为你精心安排，祝旅途愉快。</div>
              )}
            </div>

            {planId && (
              <div className="trip-metaform">
                <div className="trip-mfield">
                  <label className="trip-mlabel" htmlFor="trip-hotel">住宿</label>
                  <input id="trip-hotel" className="trip-minput" value={hotel} placeholder="记录酒店名称、价格…"
                    onChange={e => { setHotel(e.target.value); setMetaDirty(true); }} />
                </div>
                <div className="trip-mfield">
                  <label className="trip-mlabel" htmlFor="trip-notes">备注</label>
                  <textarea id="trip-notes" className="trip-minput" value={notes} rows={2}
                    placeholder="特别要求、注意事项…"
                    onChange={e => { setNotes(e.target.value); setMetaDirty(true); }} />
                </div>
                {metaDirty && (
                  <button className="tm-btn tm-btn--primary tm-btn--sm trip-msave" disabled={metaSaving} onClick={handleSaveMeta}>
                    {metaSaving ? "保存中…" : "保存行程备注"}
                  </button>
                )}
              </div>
            )}

            {plan.logs && plan.logs.length > 0 && (
              <details className="trip-log">
                <summary>规划过程日志（{plan.logs.length} 步）</summary>
                <ul>{plan.logs.map((l, i) => <li key={i}>{l}</li>)}</ul>
              </details>
            )}
          </div>

          <div className="trip-map-col">
            <MapPanel day={day} dayIdx={dayIdx} navPair={activeNavPair}
              onNavClear={() => { setActiveNavKey(null); setActiveNavPair(null); }} />
          </div>
        </div>

        {!editing && (
          <div className="trip-modbar">
            <div className="trip-modbar-inner">
              <div style={{ flex: 1 }}>
                <div className="trip-modbar-label">对行程有意见？直接说，我来改</div>
                <textarea className="tm-textarea" rows={1}
                  placeholder="例如：第 2 天把玄武湖换成颐和路，景点别太多"
                  value={modQuery} onChange={(e) => setModQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) startModify(); }} />
              </div>
              <button className="tm-btn tm-btn--primary" onClick={startModify} disabled={!modQuery.trim()}>
                修改规划 <span>→</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </React.Fragment>
  );
}

/* ── 历史行程页 ───────────────────────────────────── */
function HistoryPage({ onOpenPlan, currentUsername }) {
  const [trips, setTrips] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [openingId, setOpeningId] = React.useState(null);
  const [openError, setOpenError] = React.useState("");

  React.useEffect(() => {
    getHistory().then(data => {
      setTrips(Array.isArray(data) ? data : []);
      setLoading(false);
    }).catch(() => { setTrips([]); setLoading(false); });
  }, []);

  const open = async (trip) => {
    if (openingId) return;
    setOpeningId(trip.id);
    setOpenError("");
    try {
      const data = await getHistoryItem(trip.id);
      if (data && data.plan) onOpenPlan && onOpenPlan(data.plan, trip.id);
      else setOpenError("行程读取失败，请稍后重试");
    } catch (error) {
      setOpenError(error?.message || "行程读取失败，请稍后重试");
    } finally {
      setOpeningId(null);
    }
  };

  return (
    <div className="tm-page">
      <div className="pg-head">
        <div>
          <div className="tm-eyebrow">Archive · 过往旅程</div>
          <h1 className="pg-title">历史行程</h1>
        </div>
        {!loading && trips && (
          <div className="pg-note">共 {trips.length} 期<br />点击封面回看</div>
        )}
      </div>

      {openError && <div className="arc-error" role="alert">⚠ {openError}</div>}

      {loading && (
        <div className="arc-skeleton">
          {[1, 2, 3, 4].map(i => <div key={i} className="arc-skel-card" />)}
        </div>
      )}

      {!loading && trips && trips.length === 0 && (
        <div className="arc-empty">
          <div className="arc-empty-num">00</div>
          <div className="arc-empty-title">还没有行程记录</div>
          <p>新建一趟旅行，这里就会开始积累你的旅程档案。</p>
        </div>
      )}

      {!loading && trips && trips.length > 0 && (
        <div className="arc-grid">
          {trips.map((t, idx) => {
            const dest = t.destination || "旅行";
            const encDest = encodeURIComponent(dest);
            const imgUrl = `https://picsum.photos/seed/${encDest}-${t.id}/900/1000`;
            const dates = (() => {
              const s = t.start_date ? t.start_date.replace(/-/g, ".").slice(2) : "";
              const e = t.end_date ? t.end_date.replace(/-/g, ".").slice(2) : "";
              return s && e ? `${s} — ${e}` : (t.created_at || "").slice(0, 10);
            })();
            const daysCount = t.days_count ||
              (t.start_date && t.end_date
                ? Math.ceil((new Date(t.end_date) - new Date(t.start_date)) / 86400000) + 1
                : 1);
            const isModified = !!t.parent_id;

            return (
              <button
                key={t.id}
                className={`arc-card${idx === 0 ? " arc-card--feature" : ""}`}
                onClick={() => open(t)}
              >
                {openingId === t.id && <div className="arc-opening">正在打开…</div>}
                <div className="arc-img">
                  <i style={{ backgroundImage: `url('${imgUrl}')` }} />
                  <div className="arc-veil" />
                  <span className="arc-vol">Vol.{String(idx + 1).padStart(2, "0")} · {daysCount} Days</span>
                  <span className="arc-dest">{dest}</span>
                </div>
                <div className="arc-body">
                  <div className="arc-caption">
                    <span>{dates}</span>
                    <span>{daysCount} 天行程</span>
                  </div>
                  {isModified && (
                    <div className="arc-tags"><span className="arc-tag is-modified">修改版</span></div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── 画像页 ──────────────────────────────────────── */
function TagEditor({ label, hint, tags, onChange }) {
  const [val, setVal] = React.useState("");

  const add = () => {
    const v = val.trim().replace(/[,，]$/, "");
    if (v && !tags.includes(v)) onChange([...tags, v]);
    setVal("");
  };

  const remove = (t) => onChange(tags.filter(x => x !== t));

  return (
    <div className="pf-field">
      <div className="pf-field-label">
        <span>{label}</span>
        <span className="pf-hint">{hint}</span>
      </div>
      <div className="pf-tageditor">
        {tags.map((t) => (
          <span key={t} className="tm-tag">
            {t}
            <button onClick={() => remove(t)} aria-label={`删除 ${t}`}>✕</button>
          </span>
        ))}
        <input className="pf-taginput" value={val} placeholder="输入后回车添加…"
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === "," || e.key === "，") { e.preventDefault(); add(); } }}
          onBlur={() => val.trim() && add()} />
      </div>
    </div>
  );
}

function ProfilePage({ currentUsername }) {
  const [prefs, setPrefs] = React.useState({
    attraction_prefs: [],
    food_prefs: [],
    habit_prefs: [],
    visited_destinations: [],
  });
  const [stats, setStats] = React.useState({ trips: 0, cities: 0 });
  const [saved, setSaved] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  // 用户改过标签且未保存时为 true，此时自动刷新不覆盖编辑中的内容
  const dirtyRef = React.useRef(false);

  const applyProfile = (data) => {
    setPrefs({
      attraction_prefs: data.attraction_prefs || [],
      food_prefs: data.food_prefs || [],
      habit_prefs: data.habit_prefs || [],
      visited_destinations: data.visited_destinations || [],
    });
    setStats({
      trips: data.trip_count || 0,
      cities: (data.visited_destinations || []).length,
    });
  };

  // 画像更新 Agent 在规划完成后异步落库，停留本页时靠聚焦/轮询拉到最新画像
  const refreshProfile = async () => {
    if (dirtyRef.current) return;
    try {
      const data = await getProfile();
      if (data && !dirtyRef.current) applyProfile(data);
    } catch {}
  };

  React.useEffect(() => {
    refreshProfile().finally(() => setLoading(false));
    const onVisible = () => { if (!document.hidden) refreshProfile(); };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    const timer = setInterval(refreshProfile, 15000);
    return () => {
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
      clearInterval(timer);
    };
  }, []);

  const save = async () => {
    try {
      const data = await saveProfile(prefs);
      dirtyRef.current = false;
      if (data) applyProfile(data);
      setSaved(true);
      setTimeout(() => setSaved(false), 2200);
    } catch (e) {
      alert(e.message || "保存失败");
    }
  };

  const fields = [
    { key: "attraction_prefs", label: "喜欢的旅行主题", hint: "回车或逗号添加" },
    { key: "habit_prefs",      label: "节奏与游玩方式",  hint: "影响每天的景点数量" },
    { key: "food_prefs",       label: "饮食偏好 / 忌口",  hint: "用于餐厅推荐" },
    { key: "visited_destinations", label: "去过的城市", hint: "规划时作为参考" },
  ];

  const username = currentUsername || getAuth()?.username || "旅行者";
  const prefCount = prefs.attraction_prefs.length + prefs.food_prefs.length + prefs.habit_prefs.length;

  return (
    <div className="tm-page">
      <div className="pg-head">
        <div>
          <div className="tm-eyebrow">Profile · 旅行画像</div>
          <h1 className="pg-title">我的旅行画像</h1>
        </div>
        <div className="pg-note">这些偏好会在每次规划时<br />自动作为默认参考</div>
      </div>

      <div className="pf-grid">
        <aside className="pf-rail">
          <div className="tm-eyebrow">Traveler</div>
          <div className="pf-name">{username}</div>
          <div className="pf-sub">已记录 {stats.cities} 座城市 · {stats.trips} 趟旅程</div>
          <div className="pf-stats">
            <div className="pf-stat"><div className="pf-num">{stats.trips}</div><div className="pf-label">趟旅程</div></div>
            <div className="pf-stat"><div className="pf-num">{stats.cities}</div><div className="pf-label">座城市</div></div>
            <div className="pf-stat"><div className="pf-num">{prefCount}</div><div className="pf-label">个偏好</div></div>
          </div>
          <p className="pf-sub" style={{ marginTop: 20, lineHeight: 1.85 }}>
            规划时会自动带入这些偏好；如果你在需求里说了不一样的想法，以你的需求为准。
          </p>
        </aside>

        <div>
          {loading ? (
            <div className="pf-loading">Loading …</div>
          ) : (
            fields.map(f => (
              <TagEditor
                key={f.key}
                label={f.label}
                hint={f.hint}
                tags={prefs[f.key]}
                onChange={(v) => { dirtyRef.current = true; setPrefs(p => ({ ...p, [f.key]: v })); }} />
            ))
          )}
          <div className="pf-actions">
            <button className="tm-btn tm-btn--primary" onClick={save} disabled={loading}>保存画像</button>
            <span className={`pf-saved${saved ? " is-show" : ""}`}>✓ 已保存，下次规划自动生效</span>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { PlanPage, TripDetailPage, HistoryPage, ProfilePage, AuthModal });



