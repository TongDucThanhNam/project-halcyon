"""Authoritative HUD counters, using independently measured CE channels.

HUD ELF 957c98 reads kills/deaths from base attributes 41/42, assists from
resource 11 and farm from resource 14. This first slice implements kills,
deaths and actual lane/ordinary-jungle last hits. Assist eligibility remains
unimplemented until its rule is established; it is not inferred from 1165.
"""
from dataclasses import dataclass
import struct

if __package__:
    from . import roster
else:
    import roster


@dataclass
class PlayerScore:
    kills: int = 0
    deaths: int = 0
    farm: int = 0


def base_counter(eid: int, attribute: int, amount: int) -> tuple[int, bytes]:
    # 1052 field 13 selects the base (0), NOT the equipment bonus (1).
    return 1052, struct.pack('>IIfBB', eid, 0xffffffff, amount, attribute, 0) + bytes(8)


class Scoreboard:
    def __init__(self, hero_eids):
        self.players = {eid: PlayerScore() for eid in hero_eids}

    def hero_death(self, victim: int, killer: int) -> list[tuple[int, bytes]]:
        score = self.players[victim]
        score.deaths += 1
        frames = [base_counter(victim, 42, 1)]
        if killer in self.players and killer != victim:
            self.players[killer].kills += 1
            frames.append(base_counter(killer, 41, 1))
        return frames

    def last_hit(self, killer: int) -> list[tuple[int, bytes]]:
        if killer not in self.players:
            return []
        self.players[killer].farm += 1
        return [(1053, roster.build_hero_stat(killer, 1, 14, tail=bytes((0, 1, 0, 0, 0))))]

    def reconnect_frames(self, eid: int) -> list[tuple[int, bytes]]:
        score = self.players[eid]
        frames = [base_counter(eid, attr, amount)
                  for attr, amount in ((41, score.kills), (42, score.deaths)) if amount]
        if score.farm:
            frames.append((1053, roster.build_hero_stat(eid, score.farm, 14,
                                                      tail=bytes((0, 1, 0, 0, 0)))))
        return frames
