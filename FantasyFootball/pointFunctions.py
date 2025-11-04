# ---- Fantasy Points Calculation
SCORING_MODE = "ppr"  # default, can be "ppr", "half_ppr", or "standard"

def calculate_qb(stats):
    points = 0
    points += stats.get('pass_yd', 0) / 25
    points += stats.get('pass_td', 0) * 4
    points += stats.get('rush_yd', 0) / 10
    points += stats.get('rec_yd', 0) / 10
    points += stats.get('rush_td', 0) * 6
    points += stats.get('rec_td', 0) * 6
    points += stats.get('fum_lost', 0) * -2
    points -= stats.get('int', 0) * 2
    return round(points, 2)

def calculate_rb_wr_te(stats, scoring_mode="ppr"):
    points = 0
    points += stats.get('rush_yd', 0) / 10
    points += stats.get('rec_yd', 0) / 10
    points += stats.get('rush_td', 0) * 6
    points += stats.get('rec_td', 0) * 6

    # Receptions depend on scoring mode
    rec = stats.get('rec', 0)
    if scoring_mode == "ppr":
        points += rec * 1
    elif scoring_mode == "half_ppr":
        points += rec * 0.5
    elif scoring_mode == "standard":
        points += 0

    points += stats.get('fum_lost', 0) * -2
    return round(points, 2)

def calculate_k(stats):
    points = 0
    points += stats.get('fgm_yds_0_19', 0) * 3
    points += stats.get('fgm_yds_20_29', 0) * 3
    points += stats.get('fgm_yds_30_39', 0) * 3
    points += stats.get('fgm_yds_40_49', 0) * 4
    points += stats.get('fgm_yds_50_plus', 0) * 5
    points += stats.get('xpm', 0) * 1
    points -= stats.get('fga_missed', 0) * 1
    return round(points, 2)

def calculate_def(stats):
    points = 0
    points += stats.get("sack", 0) * 1
    points += stats.get("int", 0) * 2
    points += stats.get("fum_rec", 0) * 2
    points += stats.get("td", 0) * 6
    points += stats.get("sfty", 0) * 2

    # Points allowed adjustment
    pa = stats.get("pts_allowed", 0)
    if pa == 0:
        points += 10
    elif pa <= 6:
        points += 7
    elif pa <= 13:
        points += 4
    elif pa <= 20:
        points += 1
    elif pa <= 27:
        points += 0
    elif pa <= 34:
        points -= 1
    else:
        points -= 4

    return round(points, 2)

def calculate_points(stats, position, scoring_mode=SCORING_MODE):
    if position == 'QB':
        return calculate_qb(stats)
    elif position in ['RB', 'WR', 'TE']:
        return calculate_rb_wr_te(stats, scoring_mode)
    elif position == 'K':
        return calculate_k(stats)
    elif position == 'DEF':
        return calculate_def(stats)
    else:
        return 0