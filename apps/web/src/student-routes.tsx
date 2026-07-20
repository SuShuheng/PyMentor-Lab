import {
  Bell,
  BookBookmark,
  CaretDown,
  ChartBar,
  Code,
  Graph,
  House,
  MagnifyingGlass,
  MapTrifold,
  SignOut,
  UserCircle,
} from "@phosphor-icons/react";
import {
  getDueReviewsApiV1ReviewsDueGet,
  getTodayApiV1LearningTodayGet,
  type ReviewView,
  type TodayItem,
} from "@pymentor/api-client";
import { AppShell, StatePanel } from "@pymentor/ui";
import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { LoginPage, RegisterPage } from "./features/auth/auth-pages";
import {
  AuthProvider,
  type AuthApi,
  type AuthSession,
  useAuth,
} from "./features/auth/auth-session";
import { OnboardingPage, ProfilePage } from "./features/onboarding/onboarding-pages";
import {
  GrowthPage,
  LearningGraphPage,
  LearningMapPage,
  TodayPage,
} from "./features/learning/learning-pages";
import { NotebookPage, TracePage } from "./features/notebook/notebook-pages";
import { PracticePage } from "./features/practice/practice-pages";
import { OralExplanationPage } from "./features/resources/oral-explanation-page";
import {
  ResourceDetailPage,
  ResourcesPage,
  TutorPage,
} from "./features/resources/resource-tutor-pages";
import { configureStudentApi, studentAuthorization } from "./student-api";

const navigation = [
  {
    href: "/today",
    label: "今日学习",
    icon: <House size={22} weight="fill" />,
  },
  { href: "/lab", label: "代码实验", icon: <Code size={22} /> },
  { href: "/map", label: "学习地图", icon: <MapTrifold size={22} /> },
  // Stage C1 (problem 6 + 7): 知识图谱 and 个性化资源 get their own sidebar
  // entries. Previously they were only reachable via small buttons inside
  // sibling pages, so students had no primary path to them. `/map/graph` is
  // listed before `/resources` simply for visual grouping after the map.
  { href: "/map/graph", label: "知识图谱", icon: <Graph size={22} /> },
  {
    href: "/resources",
    label: "个性化资源",
    icon: <BookBookmark size={22} />,
  },
  {
    href: "/growth",
    label: "我的成长",
    icon: <ChartBar size={22} weight="fill" />,
  },
] as const;

/**
 * Dismisses `setOpen(false)` when a pointer lands outside `wrapperRef` or the
 * user presses Escape. Mirrors the FE-012 admin dropdown dismissal pattern
 * (controlled menu + outside-click + Escape).
 */
function useMenuDismiss(
  open: boolean,
  setOpen: (next: boolean) => void,
  wrapperRef: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    if (!open) return;
    function handlePointer(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handlePointer);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handlePointer);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open, setOpen, wrapperRef]);
}

type NotificationState = {
  dueReviews: ReviewView[];
  todayTasks: TodayItem[];
};

function StudentHeader() {
  const { session, signOut } = useAuth();
  const navigate = useNavigate();
  const [openMenu, setOpenMenu] = useState<"none" | "notifications" | "profile">(
    "none",
  );
  const notificationRef = useRef<HTMLDivElement | null>(null);
  const profileRef = useRef<HTMLDivElement | null>(null);
  const [notifications, setNotifications] = useState<NotificationState | null>(null);

  const notificationsOpen = openMenu === "notifications";
  const profileOpen = openMenu === "profile";
  const setNotificationsOpen = (next: boolean) =>
    setOpenMenu(next ? "notifications" : "none");
  const setProfileOpen = (next: boolean) => setOpenMenu(next ? "profile" : "none");

  useMenuDismiss(notificationsOpen, setNotificationsOpen, notificationRef);
  useMenuDismiss(profileOpen, setProfileOpen, profileRef);

  // Lazily load notification data only when the bell is opened, mirroring the
  // other pages' direct client.fetch + configureStudentApi pattern (the web
  // app does not use TanStack Query hooks). Empty data sources render the
  // honest "暂无新通知" state.
  useEffect(() => {
    if (!notificationsOpen) return;
    const accessToken = session?.accessToken;
    if (!accessToken) {
      setNotifications({ dueReviews: [], todayTasks: [] });
      return;
    }
    let active = true;
    configureStudentApi();
    void Promise.all([
      getDueReviewsApiV1ReviewsDueGet({ headers: studentAuthorization(accessToken) }),
      getTodayApiV1LearningTodayGet({ headers: studentAuthorization(accessToken) }),
    ])
      .then(([reviewResult, todayResult]) => {
        if (!active) return;
        // Both endpoints are read-only projections; a missing body means
        // "empty for now", so we coerce to [] rather than throwing and
        // blocking the panel.
        setNotifications({
          dueReviews: reviewResult.data ?? [],
          todayTasks: todayResult.data ?? [],
        });
      })
      .catch(() => {
        if (active) setNotifications({ dueReviews: [], todayTasks: [] });
      });
    return () => {
      active = false;
    };
  }, [notificationsOpen, session?.accessToken]);

  function handleSignOut() {
    setProfileOpen(false);
    signOut();
    navigate("/login", { replace: true });
  }

  const dueReviews = notifications?.dueReviews ?? [];
  const todayTasks = notifications?.todayTasks ?? [];
  const reviewTasks = todayTasks.filter((task) => task.kind === "REVIEW");
  const learningTasks = todayTasks.filter((task) => task.kind !== "REVIEW");
  const hasNotifications = dueReviews.length > 0 || todayTasks.length > 0;

  return (
    <div className="student-header">
      <button className="course-switcher" type="button">
        <span className="course-switcher__mark" aria-hidden="true">
          <Code size={22} weight="bold" />
        </span>
        <strong>Python 程序设计</strong>
        <CaretDown aria-hidden="true" size={16} />
      </button>
      <label className="student-search">
        <span className="sr-only">搜索知识点、资源或代码</span>
        <MagnifyingGlass aria-hidden="true" size={20} />
        <input placeholder="搜索知识点、资源、代码…（⌘K）" type="search" />
      </label>
      <div className="student-header__actions">
        <button
          className="task-progress"
          onClick={() => navigate("/today")}
          type="button"
        >
          <span>今日计划</span>
          <strong>服务端同步</strong>
          <span aria-label="进度见今日学习页" className="task-progress__ring" />
        </button>
        <div className="student-notifications" ref={notificationRef}>
          <button
            aria-expanded={notificationsOpen}
            aria-haspopup="menu"
            aria-label="通知"
            className="icon-button"
            onClick={() => setNotificationsOpen(!notificationsOpen)}
            type="button"
          >
            <Bell size={22} />
          </button>
          {notificationsOpen ? (
            <ul
              aria-label="通知中心"
              className="student-notifications__list"
              role="menu"
            >
              {!notifications ? (
                <li aria-label="加载通知" className="student-notifications__empty" role="menuiteminfo">
                  正在加载通知…
                </li>
              ) : !hasNotifications ? (
                <li
                  aria-label="暂无新通知"
                  className="student-notifications__empty"
                  role="menuiteminfo"
                >
                  暂无新通知
                </li>
              ) : (
                <>
                  {dueReviews.map((review) => (
                    <li key={`due-${review.id}`} role="none">
                      <button
                        className="student-notifications__item"
                        onClick={() => {
                          setNotificationsOpen(false);
                          navigate("/growth");
                        }}
                        role="menuitem"
                        type="button"
                      >
                        {/* FE Issue 6: hide raw node UUID; surface the
                            human-readable scenario key + due date instead. */}
                        <span>到期复测</span>
                        <small>
                          场景 {review.scenario_key} · {review.due_at ?? "今天"}
                        </small>
                      </button>
                    </li>
                  ))}
                  {reviewTasks.map((task) => (
                    <li key={`task-review-${task.id}`} role="none">
                      <button
                        className="student-notifications__item"
                        onClick={() => {
                          setNotificationsOpen(false);
                          navigate("/today");
                        }}
                        role="menuitem"
                        type="button"
                      >
                        <span>到期复测任务</span>
                        <small>预计 {task.estimated_minutes} 分钟</small>
                      </button>
                    </li>
                  ))}
                  {learningTasks.map((task) => (
                    <li key={`task-${task.id}`} role="none">
                      <button
                        className="student-notifications__item"
                        onClick={() => {
                          setNotificationsOpen(false);
                          navigate("/today");
                        }}
                        role="menuitem"
                        type="button"
                      >
                        <span>今日学习任务</span>
                        <small>
                          {task.kind} · 预计 {task.estimated_minutes} 分钟
                        </small>
                      </button>
                    </li>
                  ))}
                </>
              )}
            </ul>
          ) : null}
        </div>
        <div className="student-profile-menu" ref={profileRef}>
          <button
            aria-expanded={profileOpen}
            aria-haspopup="menu"
            aria-label="打开个人菜单"
            className="profile-button"
            onClick={() => setProfileOpen(!profileOpen)}
            type="button"
          >
            <UserCircle size={34} weight="duotone" />
            <CaretDown size={14} />
          </button>
          {profileOpen ? (
            <ul
              aria-label="学生个人菜单"
              className="student-profile-menu__list"
              role="menu"
            >
              <li className="student-profile-menu__session" role="menuiteminfo">
                <UserCircle size={20} />
                <div>
                  <strong>{session?.displayName ?? "学生"}</strong>
                  <small>{session?.userId}</small>
                </div>
              </li>
              <li role="none">
                <button
                  onClick={() => {
                    setProfileOpen(false);
                    navigate("/growth/profile");
                  }}
                  role="menuitem"
                  type="button"
                >
                  <ChartBar size={16} /> 我的画像
                </button>
              </li>
              <li role="none">
                <button
                  onClick={() => {
                    setProfileOpen(false);
                    navigate("/growth");
                  }}
                  role="menuitem"
                  type="button"
                >
                  <ChartBar size={16} /> 我的成长
                </button>
              </li>
              <li role="none">
                <button onClick={handleSignOut} role="menuitem" type="button">
                  <SignOut size={16} /> 退出登录
                </button>
              </li>
            </ul>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function StudentLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  // Pick the longest matching prefix so `/map/graph` wins over `/map` (both
  // are now in the sidebar). Falls back to `/today` when nothing matches.
  const activeHref =
    [...navigation]
      .filter((item) => location.pathname.startsWith(item.href))
      .sort((a, b) => b.href.length - a.href.length)[0]?.href ?? "/today";

  return (
    <AppShell
      activeHref={activeHref}
      brand="灵蟒智学"
      header={<StudentHeader />}
      navigation={navigation}
      onNavigate={navigate}
      status={{ label: "AI 助教 · 按需连接", detail: "连接状态在辅导会话内显示" }}
    >
      <Routes>
        <Route path="/today" element={<TodayPage />} />
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="/lab/trace" element={<TracePage />} />
        <Route path="/lab/*" element={<NotebookPage />} />
        <Route path="/practice/:nodeId" element={<PracticePage />} />
        <Route path="/oral/:nodeId" element={<OralExplanationPage />} />
        <Route path="/map/graph" element={<LearningGraphPage />} />
        <Route path="/map/*" element={<LearningMapPage />} />
        <Route path="/growth/profile" element={<ProfilePage />} />
        <Route path="/growth/*" element={<GrowthPage />} />
        <Route path="/resources/micro-lecture" element={<ResourceDetailPage />} />
        <Route path="/resources/knowledge-card" element={<ResourceDetailPage />} />
        <Route path="/resources/*" element={<ResourcesPage />} />
        <Route path="/tutor" element={<TutorPage />} />
        <Route
          path="*"
          element={
            <StatePanel
              actionLabel="返回今日学习"
              description="此页面不存在或你暂时没有访问权限"
              onAction={() => undefined}
              state="error"
              title="找不到页面"
            />
          }
        />
      </Routes>
    </AppShell>
  );
}

function RequireStudent({ children }: { children: ReactNode }) {
  const { session, status } = useAuth();

  if (status === "checking") {
    return (
      <StatePanel description="正在安全恢复你的登录状态" state="loading" title="检查登录会话" />
    );
  }
  if (status !== "authenticated" || !session) {
    return <Navigate replace to="/login" />;
  }
  if (session.role === "admin") {
    return (
      <StatePanel
        description="管理员账号请使用独立管理端登录"
        state="error"
        title="当前账号不能进入学生端"
      />
    );
  }
  return children;
}

function StudentRouteTree() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/" element={<Navigate replace to="/today" />} />
      <Route
        path="*"
        element={
          <RequireStudent>
            <StudentLayout />
          </RequireStudent>
        }
      />
    </Routes>
  );
}

export function StudentRoutes({
  api,
  initialSession,
}: {
  api?: AuthApi;
  initialSession?: AuthSession | null;
}) {
  return (
    <AuthProvider api={api} initialSession={initialSession}>
      <StudentRouteTree />
    </AuthProvider>
  );
}
