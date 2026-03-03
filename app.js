/**
 * Warsaw Cinema Aggregator
 * Premium Frontend Logic v2.0
 */

document.addEventListener('DOMContentLoaded', async () => {
    const moviesGrid = document.getElementById('movies-grid');
    const dateSelector = document.getElementById('date-selector');
    const searchInput = document.getElementById('movie-search');
    const lastUpdateSpan = document.getElementById('last-update');
    const syncButton = document.getElementById('sync-button');
    const cinemaListUl = document.getElementById('cinema-list');
    const searchAllDates = document.getElementById('search-all-dates');

    let allScreenings = [];
    let state = {
        selectedDate: null, // YYYY-MM-DD
        searchQuery: '',
        selectedCinemas: [], // Array of cinema_ids
        searchAll: false
    };

    // 1. Fetch Data
    try {
        const response = await fetch('dist/showtimes.json');
        if (!response.ok) throw new Error('Data file not found');
        const data = await response.json();

        allScreenings = data.screenings;
        state.lastGenerated = new Date(data.generated_at);

        // Formatted timestamp
        updateSyncUI();

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
        const cinemasSet = new Map();
        allScreenings.forEach(s => {
            cinemasSet.set(s.cinema_id, s.cinema_name);
        });

        // Generate UI components
        renderDateSelector(uniqueDates);
        renderCinemaCheckboxes(cinemasSet);
        renderCinemasList(cinemasSet);

        // Initial Render
        applyFilters();

        // Event Listeners
        searchInput.addEventListener('input', (e) => {
            state.searchQuery = e.target.value.toLowerCase();
            applyFilters();
        });

        searchAllDates.addEventListener('change', (e) => {
            state.searchAll = e.target.checked;
            dateSelector.style.opacity = state.searchAll ? '0.2' : '1';
            dateSelector.style.filter = state.searchAll ? 'grayscale(1)' : 'none';
            dateSelector.style.pointerEvents = state.searchAll ? 'none' : 'auto';
            applyFilters();
        });

        syncButton.addEventListener('click', handleSync);
    }

    function updateSyncUI() {
        if (!state.lastGenerated) return;

        const now = new Date();
        const diffMs = now - state.lastGenerated;
        const diffHours = diffMs / (1000 * 60 * 60);

        lastUpdateSpan.textContent = `Sync: ${state.lastGenerated.toLocaleDateString()} ${state.lastGenerated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;

        if (diffHours < 1) {
            const remainingMins = Math.ceil(60 - (diffMs / 60000));
            syncButton.disabled = true;
            syncButton.title = `Sync dostępny za ${remainingMins} min`;
        } else {
            syncButton.disabled = false;
            syncButton.title = "Uruchom ponowne skanowanie kin (GitHub Actions)";
        }
    }

    async function handleSync() {
        // 1. Double check throttling
        const now = new Date();
        if (now - state.lastGenerated < 3600000) return;

        syncButton.classList.add('syncing');
        syncButton.disabled = true;

        // Since we are on a static site, we can't easily trigger GH Actions securely without a token.
        // We will open the GH Actions page for the user or show a message.
        alert("Otwieram stronę GitHub Actions. Kliknij 'Run workflow' w workflow 'Daily Data Refresh', aby odświeżyć dane manualnie.");
        window.open('https://github.com/vaxit/warsaw-cinema-aggregator/actions/workflows/refresh_data.yml', '_blank');

        setTimeout(() => {
            syncButton.classList.remove('syncing');
            updateSyncUI();
        }, 2000);
    }

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

    function renderCinemaCheckboxes(cinemasMap) {
        const container = document.getElementById('cinema-checkboxes');
        container.innerHTML = '';

        const sorted = [...cinemasMap.entries()].sort((a, b) => a[1].localeCompare(b[1]));

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
                applyFilters();
            });

            if (checkbox.checked) label.classList.add('selected');

            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(name));
            container.appendChild(label);
        });
    }

    function renderCinemasList(cinemasMap) {
        cinemaListUl.innerHTML = '';
        const sorted = [...cinemasMap.values()].sort();
        sorted.forEach((name) => {
            const li = document.createElement('li');
            li.textContent = name;
            cinemaListUl.appendChild(li);
        });
    }

    function applyFilters() {
        // 1. Filter raw screenings
        const filtered = allScreenings.filter(s => {
            const dayMatch = state.searchAll || s.starts_at.startsWith(state.selectedDate);
            const queryMatch = s.title_norm.includes(state.searchQuery) || s.title_raw.toLowerCase().includes(state.searchQuery);
            const cinemaMatch = state.selectedCinemas.length === 0 || state.selectedCinemas.includes(s.cinema_id);
            return dayMatch && queryMatch && cinemaMatch;
        });

        // 2. Group by title_norm
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
            // Update title to the "cleanest" one if current has suffixes
            if (s.title_raw.length < moviesGrouped[s.title_norm].title.length) {
                moviesGrouped[s.title_norm].title = s.title_raw;
            }
            // Update duration if we found it in any screening
            if (s.duration_min && !moviesGrouped[s.title_norm].duration) {
                moviesGrouped[s.title_norm].duration = s.duration_min;
            }
            // Update poster if we found it in any screening
            if (s.poster_url && !moviesGrouped[s.title_norm].poster_url) {
                moviesGrouped[s.title_norm].poster_url = s.poster_url;
            }
            moviesGrouped[s.title_norm].screenings.push(s);
        });

        renderMovies(Object.values(moviesGrouped));
    }

    function renderMovies(movies) {
        if (movies.length === 0) {
            moviesGrid.innerHTML = '<div class="empty-state">Brak seansów pasujących do filtrów. Spróbuj zmienić datę lub kino.</div>';
            return;
        }

        moviesGrid.innerHTML = '';

        // Sort movies alphabetically
        movies.sort((a, b) => a.title.localeCompare(b.title));

        const dayNames = ['Nd', 'Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'Sb'];

        movies.forEach((movie, index) => {
            const card = document.createElement('div');
            card.className = 'movie-card';
            card.style.animationDelay = `${(index % 10) * 0.05}s`;

            // Sort screenings by time
            const sortedScreenings = [...movie.screenings].sort((a, b) => a.starts_at.localeCompare(b.starts_at));

            const langLabels = {
                'nap': 'Napisy',
                'dub': 'Dubbing',
                'voiceover': 'Lektor',
                'org': 'Oryginał',
                'ua': 'UA 🇺🇦'
            };

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
                    
                    <div class="screenings-list">
                        ${sortedScreenings.map(s => {
                        const time = s.starts_at.split('T')[1].substring(0, 5);
                        const dateObj = new Date(s.starts_at);
                        const dayName = dayNames[dateObj.getDay()];
                        const dateStr = `${dayName} ${dateObj.getDate().toString().padStart(2, '0')}/${(dateObj.getMonth() + 1).toString().padStart(2, '0')}`;

                        const langLabel = langLabels[s.language] || s.language;
                        const tags = s.tags.length > 0 ? s.tags.join(', ') : '';

                        return `
                                <a href="${s.booking_url || '#'}" class="screening-item" target="_blank" title="${s.cinema_name}">
                                    <span class="screening-time">${time}</span>
                                    <span class="screening-cinema">${s.cinema_name}</span>
                                    <div class="screening-info">
                                        <span class="lang-tag">${langLabel}</span>
                                        ${tags ? `<span class="other-tags">• ${tags}</span>` : ''}
                                        ${state.searchAll ? `<span class="screening-date">${dateStr}</span>` : ''}
                                    </div>
                                </a>
                            `;
                    }).join('')}
                    </div>
                </div>
            `;

            moviesGrid.appendChild(card);
        });
    }
});
