import { AuthScreen } from "@/features/auth/auth-screen"
import { useAuth } from "@/features/auth/auth-queries"
import { DashboardScreen } from "@/features/dashboard/dashboard-screen"

export function App() {
  const {
    currentUserQuery,
    isAuthenticated,
    loginMutation,
    logout,
    signupMutation,
    token,
  } = useAuth()

  return isAuthenticated && token ? (
    <DashboardScreen
      currentUser={currentUserQuery.data}
      error={currentUserQuery.error}
      isLoading={currentUserQuery.isLoading}
      onLogout={logout}
      token={token}
    />
  ) : (
    <AuthScreen
      onLogin={loginMutation.mutate}
      onSignup={signupMutation.mutate}
      isLoginPending={loginMutation.isPending}
      isSignupPending={signupMutation.isPending}
      loginError={loginMutation.error}
      signupError={signupMutation.error}
    />
  )
}

export default App
