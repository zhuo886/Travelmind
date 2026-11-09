// main.jsx — App 外壳：导航 / 认证 / 路由 / 页脚

const NAV_ITEMS = [
  { key: "plan", label: "新建规划" },
  { key: "detail", label: "行程详情" },
  { key: "history", label: "历史行程" },
  { key: "profile", label: "旅行画像" },
];

function App() {
  const [page, setPage] = React.useState("plan");
  const [planKey, setPlanKey] = React.useState(0);
  const [authUser, setAuthUser] = React.useState(() => getAuth()?.username || null);
  const [showAuthModal, setShowAuthModal] = React.useState(false);
  const [authReason, setAuthReason] = React.useState("");
  const [showUserMenu, setShowUserMenu] = React.useState(false);
  // 行程详情页数据
  const [detailPlan, setDetailPlan] = React.useState(null);
  const [detailPlanId, setDetailPlanId] = React.useState(null);
  // 触发 PlanPage 执行修改流
  const [modifyTrigger, setModifyTrigger] = React.useState(null);
  const modifyNonceRef = React.useRef(0);
  const [planPhase, setPlanPhase] = React.useState("idle");

  React.useEffect(() => {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      document.documentElement.classList.add("anim-ready");
    }));
    // 处理 URL 参数
    const params = new URLSearchParams(window.location.search);
    if (params.get("login") === "1" && !getAuth()) {
      setShowAuthModal(true);
      history.replaceState({}, "", "/");
    }
    const viewId = params.get("view_plan_id");
    if (viewId) {
      history.replaceState({}, "", "/");
      const a = getAuth();
      if (!a) { setShowAuthModal(true); return; }
      getHistoryItem(viewId).then(data => {
        if (data?.plan) {
          data.plan.__refresh_live_prices = true;
          const adapted = adaptPlan(data.plan, a.username);
          setDetailPlan(adapted);
          setDetailPlanId(viewId);
          setPage("detail");
        }
      }).catch(() => {});
    }
  }, []);

  // 页面加载时验证 token 有效性
  React.useEffect(() => {
    checkAuth().then(result => {
      if (!result) setAuthUser(null);
    });
    const onExpired = () => setAuthUser(null);
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  // 点击空白关闭用户菜单（mousedown 避免与按钮 click 冲突）
  React.useEffect(() => {
    if (!showUserMenu) return;
    const handler = (e) => {
      if (!e.target.closest(".hd-user")) {
        setShowUserMenu(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showUserMenu]);

  const go = (p) => {
    setPage(p);
    if (p === "plan") {
      setModifyTrigger(null);
      // 规划进行中时导航回来只是显示页面，不重置（保活）
      if (planPhase !== "loading") setPlanKey(k => k + 1);
    }
    window.scrollTo({ top: 0 });
  };

  // 规划/修改完成后由 PlanPage 回调，跳到行程详情页
  const onPlanReady = (plan, planId) => {
    setDetailPlan(plan);
    setDetailPlanId(planId);
    setModifyTrigger(null);
    setPage("detail");
    window.scrollTo({ top: 0 });
  };

  // 从行程详情页发起修改：跳到规划页执行修改流
  const onRequestModify = (query, planId, selectedPoiName = null) => {
    const nonce = ++modifyNonceRef.current;
    setModifyTrigger({ query, planId, selectedPoiName, nonce });
    if (planPhase !== "loading") setPlanKey(k => k + 1);
    setPage("plan");
    window.scrollTo({ top: 0 });
  };

  // 修改被放弃（concern modal 选"保留原行程"）
  const onCancelModify = () => {
    setModifyTrigger(null);
    if (detailPlan) { setPage("detail"); window.scrollTo({ top: 0 }); }
  };

  const requestLogin = (reason = "请先登录再使用规划功能") => {
    setAuthReason(reason);
    setShowAuthModal(true);
  };

  const onAuthSuccess = (username) => {
    setAuthUser(username);
    setShowAuthModal(false);
    setAuthReason("");
  };

  const logout = () => {
    clearAuth();
    setAuthUser(null);
    setShowUserMenu(false);
    setPage("plan");
    setPlanKey(k => k + 1);
  };

  const onOpenHistoryPlan = (rawPlan, planId) => {
    rawPlan.__refresh_live_prices = true;
    const adapted = adaptPlan(rawPlan, authUser);
    setDetailPlan(adapted);
    setDetailPlanId(planId);
    setPage("detail");
    window.scrollTo({ top: 0 });
  };

  const navAction = (key) => {
    if (key === "plan") { go("plan"); return; }
    if (key === "detail") {
      if (detailPlan) setPage("detail"); else go("plan");
      return;
    }
    if (key === "history") {
      if (!authUser) { requestLogin("请先登录查看历史行程"); return; }
      go("history"); return;
    }
    if (key === "profile") {
      if (!authUser) { requestLogin("请先登录管理旅行画像"); return; }
      go("profile");
    }
  };

  const initial = authUser ? authUser.slice(-1).toUpperCase() : "";

  return (
    <React.Fragment>
      <header className="hd">
        <div className="hd-brand" onClick={() => go("plan")}>
          <span className="hd-wordmark"><span className="hd-mark" />TravelMind</span>
        </div>

        <nav className="hd-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              className={`hd-link${page === item.key ? " active" : ""}`}
              onClick={() => navAction(item.key)}
            >
              {item.label}
              {item.key === "plan" && planPhase === "loading" && page !== "plan" && (
                <span className="hd-dot" title="规划进行中" />
              )}
            </button>
          ))}
        </nav>

        <div className="hd-account">
          {authUser ? (
            <div className="hd-user" onClick={(e) => { e.stopPropagation(); setShowUserMenu(v => !v); }}>
              <span className="hd-username">{authUser}</span>
              <span className="hd-avatar">{initial}</span>
              {showUserMenu && (
                <div className="hd-menu" onClick={e => e.stopPropagation()}>
                  <button onClick={logout}>退出登录</button>
                </div>
              )}
            </div>
          ) : (
            <button className="tm-btn tm-btn--quiet tm-btn--sm" onClick={() => requestLogin("")}>
              登录 / 注册
            </button>
          )}
        </div>
      </header>

      {showAuthModal && (
        <AuthModal
          reason={authReason}
          onSuccess={onAuthSuccess}
          onClose={() => { setShowAuthModal(false); setAuthReason(""); }}
        />
      )}

      <main className="tm-shell">
        {/* PlanPage 始终挂载，切换页面时隐藏而非卸载，保持规划流继续运行 */}
        <div style={{ display: page === "plan" ? "" : "none" }}>
          <PlanPage
            key={planKey}
            onRequestLogin={() => requestLogin()}
            currentUsername={authUser}
            onPhaseChange={setPlanPhase}
            onPlanReady={onPlanReady}
            modifyTrigger={modifyTrigger}
            onCancelModify={onCancelModify}
            onManageProfile={() => { if (!authUser) { requestLogin("请先登录管理旅行画像"); return; } go("profile"); }}
          />
        </div>
        {page === "detail" && detailPlan && (
          <TripDetailPage
            plan={detailPlan}
            planId={detailPlanId}
            onRequestModify={onRequestModify}
            onRequestLogin={() => requestLogin()}
            currentUsername={authUser}
          />
        )}
        {page === "history" && (
          <HistoryPage onOpenPlan={onOpenHistoryPlan} currentUsername={authUser} />
        )}
        {page === "profile" && (
          <ProfilePage currentUsername={authUser} />
        )}
      </main>

      <footer className="ft">
        <span>TravelMind</span>
        <span>多 Agent 行程编排</span>
        <span>Build 2026.11</span>
      </footer>
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
