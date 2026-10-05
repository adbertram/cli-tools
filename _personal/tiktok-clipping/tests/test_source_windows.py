import pytest
from tiktok_clipping_cli.safety import SafetyError, canonical
from tiktok_clipping_cli.source_windows import build_windows, require_window_cuts, window_record


def cues(count=1500):
 return [{'start_seconds':i*2,'end_seconds':i*2+1.5,'text':f'Exact measured word {i}.'} for i in range(count)]


def test_full_episode_partition_covers_every_original_cue_once_and_keeps_real_times():
 original=cues();windows=build_windows(original,3522)
 assert len(windows)>5 and [cue for w in windows for cue in w['transcript_segments']]==original
 assert build_windows(original,3522)==windows
 for i,w in enumerate(windows):
  assert w['ordinal']==i and w['end_seconds']-w['start_seconds']<=600
  assert len(canonical({k:w[k] for k in ('transcript','transcript_segments')}).encode())<=24576
  assert window_record(w)['window_id']==w['window_id']


def test_byte_limit_splits_without_omitting_words_or_favoring_the_first_range():
 original=[{**c,'text':'a'*1900} for c in cues(100)]
 windows=build_windows(original,200)
 assert len(windows)>10 and windows[-1]['transcript_segments'][-1]==original[-1]
 assert [cue for w in windows for cue in w['transcript_segments']]==original


@pytest.mark.parametrize('mutation',[lambda c:c[1].update(start_seconds=.5),lambda c:c[0].update(end_seconds=700),
 lambda c:c[0].update(text=''),lambda c:c[0].update(start_seconds=float('nan'))])
def test_unsupported_speech_timing_never_gets_smoothed(mutation):
 original=cues(2);mutation(original)
 with pytest.raises(SafetyError):build_windows(original,1000)


def test_cuts_must_stay_inside_explicit_original_timeline_window():
 w=window_record(build_windows(cues(),3522)[1])
 require_window_cuts(w,[{'start_seconds':w['start_seconds'],'end_seconds':w['start_seconds']+20}])
 for a,b in ((0,20),(w['end_seconds']-10,w['end_seconds']+1)):
  with pytest.raises(SafetyError,match='outside_admitted'):require_window_cuts(w,[{'start_seconds':a,'end_seconds':b}])
