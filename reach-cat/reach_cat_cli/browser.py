"""Firebase authentication through Reach.cat's own browser app."""
from cli_tools_shared.auth import BrowserAutomation

ACCOUNT_JS = r"""async () => {
    const {a:getAuth}=await import('/assets/firebase-Df3M1fEi.js');
    const auth=getAuth();
    await auth.authStateReady();
    const user=auth.currentUser;
    if(!user)return null;
    await user.getIdToken(true);
    return {uid:user.uid,email:user.email,displayName:user.displayName,emailVerified:user.emailVerified,
        onboarding_complete:/^\/signup(?:\/|$)/.test(location.pathname)?false:null};
}"""


class ReachCatBrowser(BrowserAutomation):
    SESSION_NAME = 'reach-cat'
    LOGIN_URL = 'https://reach.cat/signin'
    AUTH_CHECK_URL = 'https://reach.cat/'
    AUTH_URL_PATTERN = r'/(signin|signup)(?:/|$)'
    AUTH_LOGIN_FORM_SELECTOR = ''
    AUTH_FAILURE_PAGE_JS = "async () => {try {const account=await (" + ACCOUNT_JS + ")();return !account?.uid;}catch(_){return true;}}"
