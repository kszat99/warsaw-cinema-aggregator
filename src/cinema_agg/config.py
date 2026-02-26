from .models import Cinema

CINEMAS = [
    Cinema(
        id="wisla",
        name="Novekino Wisła",
        url="https://wisla.novekino.pl/MSI/mvc/pl",
        adapter="novekino"
    ),
    Cinema(
        id="atlantic",
        name="Novekino Atlantic",
        url="https://atlantic.novekino.pl/MSI/mvc/pl",
        adapter="novekino"
    ),
    Cinema(
        id="muranow",
        name="Kinomuranów",
        url="https://kinomuranow.pl/repertuar",
        adapter="muranow"
    ),
    Cinema(
        id="luna",
        name="Kino Luna",
        url="https://kinoluna.bilety24.pl/",
        adapter="bilety24"
    ),
    Cinema(
        id="elektronik",
        name="Kino Elektronik",
        url="https://kinoelektronik.pl/",
        adapter="bilety24"
    ),
    Cinema(
        id="kinoteka",
        name="Kinoteka",
        url="https://kinoteka.pl/repertuar/",
        adapter="kinoteka"
    ),
    Cinema(
        id="1088",
        name="Cinema City Arkadia",
        url="https://www.cinema-city.pl/",
        adapter="cinema_city"
    ),
    Cinema(
        id="1086",
        name="Cinema City Bemowo",
        url="https://www.cinema-city.pl/",
        adapter="cinema_city"
    ),
    Cinema(
        id="1089",
        name="Cinema City Sadyba",
        url="https://www.cinema-city.pl/",
        adapter="cinema_city"
    ),
    Cinema(
        id="0040",
        name="Multikino Młociny",
        url="https://www.multikino.pl/repertuar/warszawa-mlociny",
        adapter="multikino"
    ),
]

TMDB_API_KEY = "025f0e9a919ce48007c36e7cd74f4e92"
