"""Service constants shared by the CLI and private capture decoder."""
PROJECT_ID = 'weekly-6f36c'
DOCUMENT_ROOT = f'projects/{PROJECT_ID}/databases/(default)/documents'
USER_DOCUMENT_ROOT = DOCUMENT_ROOT + '/users/'
FIRESTORE_USER_URL = 'https://firestore.googleapis.com/v1/' + USER_DOCUMENT_ROOT
CLOUD_FUNCTIONS_BASE = f'https://us-central1-{PROJECT_ID}.cloudfunctions.net'
EXPORT_HEADER_NAMES = ('rangekey', 'timezoneoffset', 'summaryonly', 'excludefundcontributions', 'excludeignoredtransactions', 'excludereportexcludeditems')
