import math

import torch

from .rules import GAMES, validate_numbers


def generate_candidates(bundle, recent_draws, seed, count=4):
    cfg = bundle.config; spec = GAMES[bundle.game]
    if len(recent_draws) < cfg.window: raise ValueError("近期数据不足")
    front_input = torch.tensor([[r["front"] for r in recent_draws[-cfg.window:]]]) - 1
    back_input = torch.tensor([[r["back"] for r in recent_draws[-cfg.window:]]]) - 1
    candidates = []; seen = set()
    bundle.front.eval(); bundle.back.eval()
    with torch.inference_mode(), torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        front_emissions = bundle.front(front_input)
        back_emissions = bundle.back(back_input) if bundle.game == "dlt" else bundle.back(back_input[:, :, 0])
        for attempt in range(96):
            scale = 0. if attempt == 0 else .65
            noise = torch.distributions.Gumbel(0., 1.).sample(front_emissions.shape) * scale
            front = [n + 1 for n in bundle.front.chain.decode(front_emissions + noise, ordered=True)[0]]
            if bundle.game == "dlt":
                noise = torch.distributions.Gumbel(0., 1.).sample(back_emissions.shape) * scale
                back = [n + 1 for n in bundle.back.chain.decode(back_emissions + noise, ordered=True)[0]]
                back_score = bundle.back.chain.log_likelihood(back_emissions, torch.tensor([back]) - 1).item()
            else:
                logits = back_emissions[0].clone()
                if bundle.game == "qlc": logits[torch.tensor(front) - 1] = -10000
                index = int(torch.multinomial(logits.softmax(-1), 1)) if attempt else int(logits.argmax())
                back = [index + 1]; back_score = logits.log_softmax(-1)[index].item()
            validate_numbers(bundle.game, front, back)
            key = (tuple(front), tuple(back))
            if key in seen: continue
            seen.add(key)
            model_score = bundle.front.chain.log_likelihood(front_emissions, torch.tensor([front]) - 1).item() + back_score
            last = recent_draws[-1]["front"]
            candidates.append({"id": chr(65 + len(candidates)), "front": front, "back": back,
                "model_log_score": round(model_score, 5),
                "features": {"odd_count": sum(n % 2 for n in front), "low_count": sum(n <= spec.front_max / 2 for n in front),
                    "last_draw_overlap": len(set(front) & set(last)),
                    "consecutive_pairs": sum(b - a == 1 for a, b in zip(front, front[1:]))}})
            if len(candidates) == count: break
    if len(candidates) < 2: raise RuntimeError("无法生成足够的不同有效候选")
    return candidates
