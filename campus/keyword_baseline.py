"""Frozen pre-improvement keyword ranker used only as an evaluation baseline."""
from datetime import datetime
from .matching import availability


def rank(profile,c,at):
    if c['content_type'] not in profile.content_types:return None
    if profile.valid_until and at>=profile.valid_until:return None
    if c['starts_at'] and not availability(profile,datetime.fromisoformat(c['starts_at']),datetime.fromisoformat(c['ends_at']))[0]:return None
    if c['remaining_capacity']<=0:return None
    text=' '.join(str(c.get(k,'')) for k in ('title','subtitle','description','requirements')).casefold()
    skills=[s for s in profile.skills if s.casefold() in text]
    interests=[s for s in profile.interests if s.casefold() in text]
    locations=[s for s in profile.locations if s.casefold() in c['location'].casefold()]
    if not (skills or interests or locations):return None
    return dict(score=min(100,40*bool(skills)+30*bool(interests)+15*bool(locations)+15*bool(c['starts_at'] and (profile.available_slots or profile.weekly_slots))))
