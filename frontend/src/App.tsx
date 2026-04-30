import { AccountPanel } from "@/features/auth/account-panel"
import { AuthScreen } from "@/features/auth/auth-screen"
import { useAuth } from "@/features/auth/auth-queries"

export function App() {
  const {
    currentUserQuery,
    isAuthenticated,
    loginMutation,
    logout,
    signupMutation,
  } = useAuth()

  return isAuthenticated ? (
    <AccountPanel
      currentUser={currentUserQuery.data}
      error={currentUserQuery.error}
      isLoading={currentUserQuery.isLoading}
      onLogout={logout}
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
