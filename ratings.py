"""Five-star presentation for Plex's 0–10 user ratings."""


def filled_stars(rating):
    return max(0, min(5, int((float(rating or 0) + 1) / 2)))


def star_text(rating):
    filled = filled_stars(rating)
    return '★' * filled + '☆' * (5 - filled)


def stars_from_click(cell_x, current_rating):
    """Choose the clicked star; clicking the current one clears the rating."""
    stars = max(1, min(5, int(max(0, cell_x) / 20) + 1))
    return 0 if filled_stars(current_rating) == stars else stars
