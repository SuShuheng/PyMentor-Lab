import {
  Bell,
  CaretDown,
  ChartBar,
  Code,
  House,
  MagnifyingGlass,
  MapTrifold,
  UserCircle,
} from "@phosphor-icons/react";
import { AppShell, StatePanel } from "@pymentor/ui";
import type { ReactNode } from "react";
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
import {
  ResourceDetailPage,
  ResourcesPage,
  TutorPage,
} from "./features/resources/resource-tutor-pages";

const navigation = [
  {
    href: "/today",
    label: "今日学习",
    icon: <House size={22} weight="fill" />,
  },
  { href: "/lab", label: "代码实验", icon: <Code size={22} /> },
  { href: "/map", label: "学习地图", icon: <MapTrifold size={22} /> },
  {
    href: "/growth",
    label: "我的成长",
    icon: <ChartBar size={22} weight="fill" />,
  },
] as const;

function StudentHeader() {
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
        <button className="task-progress" type="button">
          <span>今日计划</span>
          <strong>服务端同步</strong>
          <span aria-label="进度见今日学习页" className="task-progress__ring" />
        </button>
        <button aria-label="通知" className="icon-button" type="button">
          <Bell size={22} />
        </button>
        <button aria-label="打开个人菜单" className="profile-button" type="button">
          <UserCircle size={34} weight="duotone" />
          <CaretDown size={14} />
        </button>
      </div>
    </div>
  );
}

function StudentLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeHref =
    navigation.find((item) => location.pathname.startsWith(item.href))?.href ?? "/today";

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
