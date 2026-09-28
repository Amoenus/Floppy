// Filter state behind the shared filter menu and hidden filter form
// (templates/app/components/filter_menu.html and filter_form.html).
//
// A page spreads it into its own x-data:
//   x-data="{ ...libraryFilterState(rules, filterData), sort: ..., ... }"
// `rules` is the server's normalized filter rules (lists.smart_rules keys:
// status, tag, tag_mode, rating, genre, year, ...). `filterData` is the menu's
// option payload; only its show_* flags are read here.
// eslint-disable-next-line no-unused-vars
function libraryFilterState(rules = {}, filterData = {}) {
  const value = (key, fallback = '') => rules[key] || fallback;
  return {
    statuses: [...(rules.status || [])],
    rating: value('rating', 'all'),
    rating_min: value('rating_min'),
    rating_max: value('rating_max'),
    collection: value('collection', 'all'),
    genre: value('genre'),
    implied_genre: value('implied_genre'),
    year: value('year'),
    release: value('release', 'all'),
    release_date_from: value('release_date_from'),
    release_date_to: value('release_date_to'),
    release_date_within: value('release_date_within'),
    release_date_within_unit: value('release_date_within_unit', 'days'),
    date_added_from: value('date_added_from'),
    date_added_to: value('date_added_to'),
    date_added_within: value('date_added_within'),
    date_added_within_unit: value('date_added_within_unit', 'days'),
    completed_date_from: value('completed_date_from'),
    completed_date_to: value('completed_date_to'),
    completed_date_within: value('completed_date_within'),
    completed_date_within_unit: value('completed_date_within_unit', 'days'),
    author: value('author'),
    source: value('source'),
    language: value('language'),
    country: value('country'),
    platform: value('platform'),
    origin: value('origin'),
    format: value('format'),
    provider: value('provider'),
    selectedTags: [...(rules.tag || [])],
    tagMode: value('tag_mode', 'or'),
    selectedLists: [...(rules.list || [])],
    showLanguages: Boolean(filterData.show_languages),
    showCountries: Boolean(filterData.show_countries),
    showPlatforms: Boolean(filterData.show_platforms),
    showOrigins: Boolean(filterData.show_origins),
    showFormats: Boolean(filterData.show_formats),
    showProviders: Boolean(filterData.show_providers),
    ratingLabels: {
      all: gettext('All'),
      rated: gettext('Rated'),
      not_rated: gettext('Not Rated'),
    },
    collectionLabels: {
      all: gettext('All'),
      collected: gettext('Collected'),
      not_collected: gettext('Not Collected'),
    },
    releaseLabels: {
      all: gettext('Any'),
      released: gettext('Released'),
      not_released: gettext('Not Released'),
    },
    isStatusSelected(status) {
      return this.statuses.includes(status);
    },
    toggleStatus(status) {
      this.statuses = this.statuses.includes(status)
        ? this.statuses.filter((s) => s !== status)
        : [...this.statuses, status];
    },
    isTagSelected(tag) {
      return this.selectedTags.includes(tag);
    },
    toggleTag(tag) {
      this.selectedTags = this.selectedTags.includes(tag)
        ? this.selectedTags.filter((t) => t !== tag)
        : [...this.selectedTags, tag];
    },
    cycleTagMode() {
      this.tagMode = this.tagMode === 'and' ? 'or' : (this.tagMode === 'or' ? 'not' : 'and');
    },
    formatRangeLabel(minValue, maxValue) {
      if (minValue && maxValue) return `${minValue}-${maxValue}`;
      if (minValue) return `>=${minValue}`;
      if (maxValue) return `<=${maxValue}`;
      return '';
    },
    formatDateRangeLabel(prefix, fromValue, toValue) {
      if (!fromValue && !toValue) return '';
      const fromYear = /^(\d{4})-01-01$/.exec(fromValue || '');
      const toYear = /^(\d{4})-12-31$/.exec(toValue || '');
      if (fromYear && toYear) return `${fromYear[1]}-${toYear[1]}`;
      const labelPrefix = prefix ? `${prefix} ` : '';
      if (fromValue && toValue) return `${labelPrefix}${fromValue}-${toValue}`;
      if (fromValue) return `${labelPrefix}>=${fromValue}`;
      return `${labelPrefix}<=${toValue}`;
    },
    // A completed-date range spanning exactly one calendar year reads as that year.
    completedYearLabel() {
      const from = this.completed_date_from;
      const to = this.completed_date_to;
      const year = (from || '').slice(0, 4);
      if (from && to && from === `${year}-01-01` && to === `${year}-12-31`) return year;
      return gettext('Pick a year…');
    },
    // Labels for the active attribute filters, in menu order. A page adds its
    // own (media types, linked lists) through extraFilterLabels().
    filterLabel() {
      const upperCode = (code) => (code.length <= 3 ? code.toUpperCase() : code);
      const labels = [...(this.extraFilterLabels ? this.extraFilterLabels() : [])];
      if (this.rating && this.rating !== 'all') labels.push(this.ratingLabels[this.rating]);
      labels.push(this.formatRangeLabel(this.rating_min, this.rating_max));
      if (this.collection && this.collection !== 'all') labels.push(this.collectionLabels[this.collection]);
      labels.push(this.genre);
      if (this.implied_genre) labels.push(gettext('Implied: ') + this.implied_genre);
      if (this.year) labels.push(this.year === 'unknown' ? gettext('Unknown Year') : this.year);
      if (this.release && this.release !== 'all') labels.push(this.releaseLabels[this.release]);
      labels.push(
        relativeWindowLabel(this.release_date_within, this.release_date_within_unit)
          || this.formatDateRangeLabel(gettext('Release'), this.release_date_from, this.release_date_to),
        relativeWindowLabel(this.date_added_within, this.date_added_within_unit)
          || this.formatDateRangeLabel(gettext('Added'), this.date_added_from, this.date_added_to),
        relativeWindowLabel(this.completed_date_within, this.completed_date_within_unit)
          || this.formatDateRangeLabel(gettext('Completed'), this.completed_date_from, this.completed_date_to),
        this.author,
        this.source.toUpperCase(),
      );
      if (this.showLanguages && this.language) labels.push(upperCode(this.language));
      if (this.showCountries && this.country) labels.push(upperCode(this.country));
      if (this.showPlatforms) labels.push(this.platform);
      if (this.showOrigins && this.origin) labels.push(upperCode(this.origin));
      if (this.showFormats && this.format) {
        labels.push(this.format === 'ebook' ? 'eBook' : this.format.charAt(0).toUpperCase() + this.format.slice(1));
      }
      if (this.showProviders) labels.push(this.provider);
      if (this.selectedTags.length) {
        const prefix = this.tagMode === 'not' ? '-' : '+';
        labels.push(prefix + this.selectedTags.join(this.tagMode === 'and' ? ' & ' : ', '));
      }
      const active = labels.filter(Boolean);
      if (active.length === 0) return gettext('All');
      return active.length === 1 ? active[0] : `${active[0]} +${active.length - 1}`;
    },
    clearFilters() {
      Object.assign(this, {
        rating: 'all',
        rating_min: '',
        rating_max: '',
        collection: 'all',
        genre: '',
        implied_genre: '',
        year: '',
        release: 'all',
        release_date_from: '',
        release_date_to: '',
        release_date_within: '',
        date_added_from: '',
        date_added_to: '',
        date_added_within: '',
        completed_date_from: '',
        completed_date_to: '',
        completed_date_within: '',
        author: '',
        source: '',
        language: '',
        country: '',
        platform: '',
        origin: '',
        format: '',
        provider: '',
        selectedTags: [],
        tagMode: 'or',
        selectedLists: [],
      });
    },
  };
}
