"""Clerk sign-in through the same public campaign page used by the website."""
from cli_tools_shared.auth import BrowserAutomation


ACCOUNT_JS = """async () => {
                const until=Date.now()+10000;
                while(!window.Clerk?.loaded && Date.now()<until)await new Promise(resolve=>setTimeout(resolve,100));
                if(!window.Clerk?.session)return null;
                const token=await window.Clerk.session.getToken({template:'convex'});
                if(!token)return null;
                const response=await fetch('https://dapper-duck-781.convex.cloud/api/query',{
                    method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
                    body:JSON.stringify({path:'users:current',format:'convex_encoded_json',args:[{}]})});
                if(!response.ok)return null;
                const result=await response.json();
                return result.status==='success'?result.value:null;
            }"""

class PromoteFunBrowser(BrowserAutomation):
    SESSION_NAME = 'promote-fun'
    LOGIN_URL = 'https://www.promote.fun/campaigns'
    AUTH_CHECK_URL = 'https://www.promote.fun/campaigns'
    AUTH_URL_PATTERN = r'/sso-callback(?:/|$)'
    AUTH_LOGIN_FORM_SELECTOR = ''
    AUTH_FAILURE_PAGE_JS = "async () => {try {const account=await (" + ACCOUNT_JS + ")();return typeof account?._id!=='string';}catch(_){return true;}}"
