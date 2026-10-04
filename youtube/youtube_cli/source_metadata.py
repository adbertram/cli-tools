"""Public exact-video facts without format inventories or signed URLs."""
from datetime import datetime, timezone
import json
import math
import re
import shutil
from urllib.parse import parse_qs, urlparse

from cli_tools_shared.bounded_read import run_bounded_read
from .client import ClientError

FACTS={'id','title','duration','channel','channel_id','upload_date'}
TEMPLATE='%(.{id,title,duration,channel,channel_id,upload_date})j'


class SourceMetadataError(ClientError):
    def __init__(self,code,category='transient'):
        super().__init__(code)
        self.code=code;self.category=category;self.status=None;self.retry_after_seconds=None


def canonical_video(value):
    try:
        if type(value) is not str or len(value)>2048:raise ValueError()
        parsed=urlparse(value);query=parse_qs(parsed.query,keep_blank_values=True)
        if parsed.scheme!='https' or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None,443):raise ValueError()
        if 'si' in query and (len(query['si'])!=1 or not re.fullmatch('[A-Za-z0-9_-]{1,256}',query['si'][0])):raise ValueError()
        if parsed.hostname in ('youtube.com','www.youtube.com') and parsed.path=='/watch' and set(query)-{'si'}=={'v'} and len(query['v'])==1:
            identifier=query['v'][0]
        elif parsed.hostname=='youtu.be' and set(query)<={'si'}:identifier=parsed.path[1:]
        else:raise ValueError()
        if not re.fullmatch('[A-Za-z0-9_-]{11}',identifier):raise ValueError()
        return identifier,'https://www.youtube.com/watch?v='+identifier
    except (ValueError,TypeError):raise SourceMetadataError('source_video_url_invalid','invalid_request') from None


def language_codes(value):
    # NA is the extractor's missing/empty marker, not proof a transcript exists.
    if value=='NA':return None
    codes=[v.strip() for v in value.split(',')]
    if len(codes)>512 or len(set(codes))!=len(codes) or any(not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',v) for v in codes):
        raise SourceMetadataError('source_caption_language_schema_changed','invalid_data')
    return sorted(codes)


def get_source_metadata(url,*,timeout_seconds,max_bytes):
    if type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or not .75<timeout_seconds<=3600:raise SourceMetadataError('source_metadata_timeout_invalid','invalid_request')
    identifier,canonical=canonical_video(url)
    executable=shutil.which('yt-dlp')
    if executable is None:raise SourceMetadataError('source_metadata_executable_missing','not_ready')
    result=run_bounded_read([executable,'--ignore-config','--no-playlist','--skip-download',
        '--print',TEMPLATE,'--print','%(subtitles)l','--print','%(automatic_captions)l',canonical],
        timeout_seconds=timeout_seconds-.75,max_stdout_bytes=max_bytes)
    if result.returncode!=0:raise SourceMetadataError('source_metadata_read_failed')
    try:
        lines=result.stdout.decode('utf-8').splitlines()
        if len(lines)!=3:raise ValueError()
        facts=json.loads(lines[0])
        if type(facts) is not dict or set(facts)!=FACTS or facts['id']!=identifier:raise ValueError()
        for key in ('title','channel','channel_id','upload_date'):
            if type(facts[key]) is not str or not facts[key] or len(facts[key].encode())>4096:raise ValueError()
        if type(facts['duration']) not in (int,float) or not math.isfinite(facts['duration']) or facts['duration']<=0:raise ValueError()
        if not re.fullmatch('[0-9]{8}',facts['upload_date']):raise ValueError()
        datetime.strptime(facts['upload_date'],'%Y%m%d')
    except (ValueError,TypeError,KeyError,UnicodeError):raise SourceMetadataError('source_metadata_schema_changed','invalid_data') from None
    return {**facts,'observed_at':datetime.now(timezone.utc).isoformat(),
            'transcript_availability':{'manual_language_codes':language_codes(lines[1]),
                'automatic_language_codes':language_codes(lines[2]),'kind':'extractor_reported_language_codes'}}
