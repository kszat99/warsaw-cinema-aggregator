/**
 * Warsaw Cinema Aggregator
 * Frontend Logic v3.0 – Horizontal Screenings
 */

document.addEventListener('DOMContentLoaded', async () => {
    const moviesGrid = document.getElementById('movies-grid');
    const dateSelector = document.getElementById('date-selector');
    const searchInput = document.getElementById('movie-search');
    const lastUpdateSpan = document.getElementById('last-update');
    const cinemaListUl = document.getElementById('cinema-list');
    const searchAllDates = document.getElementById('search-all-dates');
    const dateScrollLeft = document.getElementById('date-scroll-left');
    const dateScrollRight = document.getElementById('date-scroll-right');

    const DAY_NAMES = ['Nd', 'Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'Sb'];
    const LANG_LABELS = {
        'nap': 'Napisy',
        'dub': 'Dubbing',
        'voiceover': 'Lektor',
        'org': 'Oryginał',
        'ua': 'UA 🇺🇦'
    };

    let allScreenings = [];
    let cinemasMap = new Map();
    let state = {
        selectedDate: null, // YYYY-MM-DD
        searchQuery: '',
        selectedCinemas: [], // Array of cinema_ids; empty = all
        searchAll: false
    };

    // 1. Fetch Data
    try {
        const response = await fetch('dist/showtimes.json');
        if (!response.ok) throw new Error('Data file not found');
        const data = await response.json();

        allScreenings = data.screenings;
        state.lastGenerated = new Date(data.generated_at);

        updateLastUpdateUI();
        initApp();
    } catch (err) {
        console.error(err);
        moviesGrid.innerHTML = `<div class="empty-state">Błąd ładowania danych: ${err.message}.<br>Upewnij się, że uruchomiłeś builder.</div>`;
    }

    function initApp() {
        // Prepare unique dates from the data
        const uniqueDates = [...new Set(allScreenings.map(s => s.starts_at.split('T')[0]))].sort();
        state.selectedDate = uniqueDates[0] || new Date().toISOString().split('T')[0];

        // Prepare unique cinemas
        allScreenings.forEach(s => {
            cinemasMap.set(s.cinema_id, s.cinema_name);
        });

        // Generate UI components
        renderDateSelector(uniqueDates);
        setupDateScrollButtons();
        renderCinemaDropdown(cinemasMap);
        renderCinemasList(cinemasMap);

        // Event Listeners (attached BEFORE initial render so they work even if render hits an issue)
        searchInput.addEventListener('input', (e) => {
            state.searchQuery = e.target.value.toLowerCase();
            applyFilters();
        });

        searchAllDates.addEventListener('change', (e) => {
            state.searchAll = e.target.checked;
            dateSelector.parentElement.style.opacity = state.searchAll ? '0.2' : '1';
            dateSelector.parentElement.style.filter = state.searchAll ? 'grayscale(1)' : 'none';
            dateSelector.parentElement.style.pointerEvents = state.searchAll ? 'none' : 'auto';
            applyFilters();
        });

        // Initial Render
        applyFilters();
    }

    // ──────────── Last Update UI ────────────

    function updateLastUpdateUI() {
        if (!state.lastGenerated) return;
        lastUpdateSpan.textContent = `Sync: ${state.lastGenerated.toLocaleDateString()} ${state.lastGenerated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    }

    // ──────────── Date Selector ────────────

    function renderDateSelector(dates) {
        dateSelector.innerHTML = '';
        const dayNames = ['nd', 'pn', 'wt', 'śr', 'cz', 'pt', 'sb'];

        dates.forEach(dateStr => {
            const dateObj = new Date(dateStr);
            const chip = document.createElement('div');
            chip.className = `date-chip ${dateStr === state.selectedDate ? 'active' : ''}`;

            chip.innerHTML = `
                <span class="day-name">${dayNames[dateObj.getDay()]}</span>
                <span class="day-number">${dateObj.getDate()}</span>
            `;

            chip.onclick = () => {
                state.selectedDate = dateStr;
                document.querySelectorAll('.date-chip').forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                applyFilters();
            };

            dateSelector.appendChild(chip);
        });
    }

    function setupDateScrollButtons() {
        if (!dateScrollLeft || !dateScrollRight) return;

        const scrollAmount = 260; // ~3 chips

        dateScrollLeft.addEventListener('click', () => {
            dateSelector.scrollBy({ left: -scrollAmount, behavior: 'smooth' });
        });

        dateScrollRight.addEventListener('click', () => {
            dateSelector.scrollBy({ left: scrollAmount, behavior: 'smooth' });
        });

        // Update arrow visibility
        function updateArrows() {
            dateScrollLeft.disabled = dateSelector.scrollLeft <= 0;
            dateScrollRight.disabled = dateSelector.scrollLeft >= dateSelector.scrollWidth - dateSelector.clientWidth - 5;
        }

        dateSelector.addEventListener('scroll', updateArrows);
        // Initial state
        setTimeout(updateArrows, 100);
    }

    // ──────────── Cinema Dropdown ────────────

    function renderCinemaDropdown(cMap) {
        const toggle = document.getElementById('cinema-dropdown-toggle');
        const panel = document.getElementById('cinema-dropdown-panel');

        if (!toggle || !panel) {
            console.warn('Cinema dropdown elements not found in DOM.');
            return;
        }

        panel.innerHTML = '';

        const sorted = [...cMap.entries()].sort((a, b) => a[1].localeCompare(b[1]));

        sorted.forEach(([id, name]) => {
            const label = document.createElement('label');
            label.className = 'cinema-item';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = id;
            checkbox.checked = state.selectedCinemas.includes(id);

            checkbox.addEventListener('change', (e) => {
                if (e.target.checked) {
                    state.selectedCinemas.push(id);
                    label.classList.add('selected');
                } else {
                    state.selectedCinemas = state.selectedCinemas.filter(cid => cid !== id);
                    label.classList.remove('selected');
                }
                updateToggleText();
                applyFilters();
            });

            if (checkbox.checked) label.classList.add('selected');

            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(name));
            panel.appendChild(label);
        });

        // Toggle dropdown open/close
        toggle.addEventListener('click', () => {
            const isOpen = panel.classList.toggle('open');
            toggle.classList.toggle('open', isOpen);
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!toggle.contains(e.target) && !panel.contains(e.target)) {
                panel.classList.remove('open');
                toggle.classList.remove('open');
            }
        });

        updateToggleText();
    }

    function updateToggleText() {
        const toggle = document.getElementById('cinema-dropdown-toggle');
        if (!toggle) return;
        const textSpan = toggle.querySelector('.toggle-text');

        if (state.selectedCinemas.length === 0) {
            textSpan.textContent = 'Wszystkie kina';
        } else {
            const names = state.selectedCinemas
                .map(id => cinemasMap.get(id))
                .filter(Boolean);
            textSpan.textContent = names.join(', ');
        }
    }

    // ──────────── Cinema Footer List ────────────

    function renderCinemasList(cMap) {
        if (!cinemaListUl) return;
        cinemaListUl.innerHTML = '';
        const sorted = [...cMap.values()].sort();
        sorted.forEach((name) => {
            const li = document.createElement('li');
            li.textContent = name;
            cinemaListUl.appendChild(li);
        });
    }

    // ──────────── Filtering ────────────

    function applyFilters() {
        const filtered = allScreenings.filter(s => {
            const dayMatch = state.searchAll || s.starts_at.startsWith(state.selectedDate);
            const queryMatch = s.title_norm.includes(state.searchQuery) || s.title_raw.toLowerCase().includes(state.searchQuery);
            const cinemaMatch = state.selectedCinemas.length === 0 || state.selectedCinemas.includes(s.cinema_id);
            return dayMatch && queryMatch && cinemaMatch;
        });

        // Group by title_norm
        const moviesGrouped = {};
        filtered.forEach(s => {
            if (!moviesGrouped[s.title_norm]) {
                moviesGrouped[s.title_norm] = {
                    title: s.title_raw,
                    duration: s.duration_min,
                    poster_url: s.poster_url,
                    screenings: []
                };
            }
            if (s.title_raw.length < moviesGrouped[s.title_norm].title.length) {
                moviesGrouped[s.title_norm].title = s.title_raw;
            }
            if (s.duration_min && !moviesGrouped[s.title_norm].duration) {
                moviesGrouped[s.title_norm].duration = s.duration_min;
            }
            if (s.poster_url && !moviesGrouped[s.title_norm].poster_url) {
                moviesGrouped[s.title_norm].poster_url = s.poster_url;
            }
            moviesGrouped[s.title_norm].screenings.push(s);
        });

        const movies = Object.values(moviesGrouped);

        if (state.searchAll) {
            renderMoviesAllDays(movies);
        } else {
            renderMovies(movies);
        }
    }

    // ──────────── Render: Single Day (horizontal strip) ────────────

    function renderMovies(movies) {
        if (movies.length === 0) {
            moviesGrid.innerHTML = '<div class="empty-state">Brak seansów pasujących do filtrów. Spróbuj zmienić datę lub kino.</div>';
            return;
        }

        moviesGrid.innerHTML = '';
        movies.sort((a, b) => a.title.localeCompare(b.title));

        movies.forEach((movie, index) => {
            const card = createMovieCard(movie, index);

            // Horizontal screening strip
            const sortedScreenings = [...movie.screenings].sort((a, b) => a.starts_at.localeCompare(b.starts_at));
            const scrollerWrapper = document.createElement('div');
            scrollerWrapper.className = 'screenings-scroller-wrapper';

            const screeningsList = document.createElement('div');
            screeningsList.className = 'screenings-list';

            sortedScreenings.forEach(s => {
                screeningsList.appendChild(createScreeningChip(s, false));
            });

            scrollerWrapper.appendChild(screeningsList);
            card.querySelector('.content-column').appendChild(scrollerWrapper);
            moviesGrid.appendChild(card);
        });
    }

    // ──────────── Render: All Days (day-grouped rows) ────────────

    function renderMoviesAllDays(movies) {
        if (movies.length === 0) {
            moviesGrid.innerHTML = '<div class="empty-state">Brak seansów pasujących do filtrów. Spróbuj zmienić datę lub kino.</div>';
            return;
        }

        moviesGrid.innerHTML = '';
        movies.sort((a, b) => a.title.localeCompare(b.title));

        movies.forEach((movie, index) => {
            const card = createMovieCard(movie, index);
            const contentCol = card.querySelector('.content-column');

            // Group screenings by day
            const byDay = {};
            movie.screenings.forEach(s => {
                const dayKey = s.starts_at.split('T')[0];
                if (!byDay[dayKey]) byDay[dayKey] = [];
                byDay[dayKey].push(s);
            });

            // Sort days
            const sortedDays = Object.keys(byDay).sort();

            sortedDays.forEach(dayKey => {
                const dayScreenings = byDay[dayKey].sort((a, b) => a.starts_at.localeCompare(b.starts_at));
                const dateObj = new Date(dayKey);
                const dayLabel = `${DAY_NAMES[dateObj.getDay()]} ${dateObj.getDate().toString().padStart(2, '0')}/${(dateObj.getMonth() + 1).toString().padStart(2, '0')}`;

                const dayGroup = document.createElement('div');
                dayGroup.className = 'day-group';

                const label = document.createElement('div');
                label.className = 'day-group-label';
                label.textContent = dayLabel;
                dayGroup.appendChild(label);

                const scrollerWrapper = document.createElement('div');
                scrollerWrapper.className = 'screenings-scroller-wrapper';

                const screeningsList = document.createElement('div');
                screeningsList.className = 'screenings-list';

                dayScreenings.forEach(s => {
                    screeningsList.appendChild(createScreeningChip(s, false));
                });

                scrollerWrapper.appendChild(screeningsList);
                dayGroup.appendChild(scrollerWrapper);
                contentCol.appendChild(dayGroup);
            });

            moviesGrid.appendChild(card);
        });
    }

    // ──────────── Shared Builders ────────────

    function createMovieCard(movie, index) {
        const card = document.createElement('div');
        card.className = 'movie-card';
        card.style.animationDelay = `${(index % 10) * 0.05}s`;

        card.innerHTML = `
            <div class="poster-column">
                ${movie.poster_url ? `<img src="${movie.poster_url}" alt="${movie.title}" loading="lazy">` :
                `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:0.8rem;">Brak plakatu</div>`}
            </div>
            <div class="content-column">
                <div class="movie-header-info">
                    <h2 class="movie-title">${movie.title}</h2>
                    <div class="movie-meta">
                        ${movie.duration ? `<span class="duration-badge">${movie.duration} min</span>` : ''}
                    </div>
                </div>
            </div>
        `;

        return card;
    }

    function createScreeningChip(s, showDate) {
        const time = s.starts_at.split('T')[1].substring(0, 5);
        const langLabel = LANG_LABELS[s.language] || s.language;
        const tags = s.tags.length > 0 ? s.tags.join(', ') : '';

        let dateHtml = '';
        if (showDate) {
            const dateObj = new Date(s.starts_at);
            const dayName = DAY_NAMES[dateObj.getDay()];
            const dateStr = `${dayName} ${dateObj.getDate().toString().padStart(2, '0')}/${(dateObj.getMonth() + 1).toString().padStart(2, '0')}`;
            dateHtml = `<span class="screening-date">${dateStr}</span>`;
        }

        const chip = document.createElement('a');
        chip.href = s.booking_url || '#';
        chip.className = 'screening-item';
        chip.target = '_blank';
        chip.title = s.cinema_name;
        chip.innerHTML = `
            <span class="screening-time">${time}</span>
            <span class="screening-cinema">${s.cinema_name}</span>
            <div class="screening-info">
                <span class="lang-tag">${langLabel}</span>
                ${tags ? `<span class="other-tags">• ${tags}</span>` : ''}
                ${dateHtml}
            </div>
        `;

        return chip;
    }
});
