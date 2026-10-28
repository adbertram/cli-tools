"""Reply form constraints must not turn a validation refusal into success."""
import pytest
from brickowl_cli.browser import BrickOwlBrowser


class Field:
    def __init__(self):
        self.value = None

    def fill(self, value):
        self.value = value

    def click(self):
        pass


class Page:
    def __init__(self, form_present=False):
        self.url = ''
        self.subject = Field()
        self.body = Field()
        self.button = Field()
        self.form_present = form_present
        self.original_subject = 'Photo request - Red Ridged Flagpole with Knights Tournament Sticker'
        self.destination = 'https://www.brickowl.com/user/99/messages'

    def goto(self, url):
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        if 'contactHref' in script:
            return {'contactHref': '/user/123/contact?reply_to=456',
                    'subject': self.original_subject}
        if '.maxLength' in script:
            return 70
        return {'url': self.url if self.form_present else self.destination,
                'formPresent': self.form_present, 'alerts': []}

    def query_selector(self, selector):
        return self.subject if selector.startswith('input[name=') else self.button

    def wait_for_selector(self, *args, **kwargs):
        return self.body


@pytest.mark.parametrize('form_present', [False, True])
def test_reply_preserves_long_prefilled_subject_and_rejects_unsent_form(form_present):
    browser = BrickOwlBrowser.__new__(BrickOwlBrowser)
    browser._page = Page(form_present)
    browser._ensure_authenticated = lambda: None
    browser.get_user_id = lambda: '99'
    if form_present:
        with pytest.raises(RuntimeError, match='contact form remains'):
            browser.reply_to_message('456', 'Hello buyer')
    else:
        assert browser.reply_to_message('456', 'Hello buyer')['success'] is True
    assert browser._page.subject.value == 'Photo request - Red Ridged Flagpole with Knights Tournament Sticker'
    assert len(browser._page.subject.value) <= 70
    assert browser._page.body.value == 'Hello buyer'


def test_reply_keeps_prefix_when_it_fits():
    browser = BrickOwlBrowser.__new__(BrickOwlBrowser)
    browser._page = Page()
    browser._page.original_subject = 'Photo request'
    browser._ensure_authenticated = lambda: None
    browser.get_user_id = lambda: '99'
    assert browser.reply_to_message('456', 'Hello buyer')['success'] is True
    assert browser._page.subject.value == 'Re: Photo request'


def test_reply_rejects_unexpected_redirect():
    browser = BrickOwlBrowser.__new__(BrickOwlBrowser)
    browser._page = Page()
    browser._page.destination = 'https://www.brickowl.com/user/login'
    browser._ensure_authenticated = lambda: None
    browser.get_user_id = lambda: '99'
    with pytest.raises(RuntimeError, match='unexpected destination'):
        browser.reply_to_message('456', 'Hello buyer')
