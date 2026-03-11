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
        id="1087",
        name="Cinema City Galeria Mokotów",
        url="https://www.cinema-city.pl/",
        adapter="cinema_city"
    ),
    Cinema(
        id="1090",
        name="Cinema City Promenada",
        url="https://www.cinema-city.pl/",
        adapter="cinema_city"
    ),
    Cinema(
        id="1096",
        name="Cinema City Galeria Północna",
        url="https://www.cinema-city.pl/",
        adapter="cinema_city"
    ),
    Cinema(
        id="1091",
        name="Cinema City Janki",
        url="https://www.cinema-city.pl/",
        adapter="cinema_city"
    ),
    Cinema(
        id="1092",
        name="Cinema City Białołęka",
        url="https://www.cinema-city.pl/",
        adapter="cinema_city"
    ),
    Cinema(
        id="1093",
        name="Cinema City Zielonka",
        url="https://www.cinema-city.pl/",
        adapter="cinema_city"
    ),
    Cinema(
        id="0040",
        name="Multikino Młociny",
        url="https://www.multikino.pl/repertuar/warszawa-mlociny",
        adapter="multikino"
    ),
    Cinema(
        id="0013",
        name="Multikino Złote Tarasy",
        url="https://www.multikino.pl/repertuar/warszawa-zlote-tarasy",
        adapter="multikino"
    ),
    Cinema(
        id="0052",
        name="Multikino Reduta",
        url="https://www.multikino.pl/repertuar/warszawa-g-city-reduta",
        adapter="multikino"
    ),
    Cinema(
        id="0024",
        name="Multikino Targówek",
        url="https://www.multikino.pl/repertuar/warszawa-g-city-targowek",
        adapter="multikino"
    ),
    Cinema(
        id="0025",
        name="Multikino Wola Park",
        url="https://www.multikino.pl/repertuar/warszawa-wola-park",
        adapter="multikino"
    ),
    Cinema(
        id="57",
        name="Helios Blue City",
        url="https://www.helios.pl/57,Warszawa/Repertuar/",
        adapter="helios"
    ),
    Cinema(
        id="iluzjon",
        name="Kino Iluzjon",
        url="https://www.iluzjon.fn.org.pl/repertuar.html",
        adapter="iluzjon"
    ),
    Cinema(
        id="kultura",
        name="Kino Kultura",
        url="https://kinokultura.bilety24.pl/",
        adapter="bilety24"
    ),
    Cinema(
        id="amondo",
        name="Kino Amondo",
        url="https://kinoamondo.pl/repertuar/",
        adapter="amondo"
    ),
    Cinema(
        id="ujazdowski",
        name="Kino Ujazdowski",
        url="https://u-jazdowski.pl/kino/repertuar",
        adapter="ujazdowski"
    ),
]

TMDB_API_KEY = "025f0e9a919ce48007c36e7cd74f4e92"
