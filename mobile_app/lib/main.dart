import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

const apiBase = String.fromEnvironment('RKL_API_BASE', defaultValue: 'http://10.0.2.2:8765');
const apiWsBase = String.fromEnvironment('RKL_API_WS_BASE');
const apiToken = String.fromEnvironment('RKL_API_TOKEN');

const _ink = Color(0xff080d13);
const _panel = Color(0xff111923);
const _panelRaised = Color(0xff172330);
const _line = Color(0xff253443);
const _mint = Color(0xff55e0b2);
const _blue = Color(0xff62a8ff);
const _amber = Color(0xffffc857);
const _muted = Color(0xff8c9bab);

enum RklThemeId { dark, light, pro, neon }

class RklThemeController extends ChangeNotifier {
  static const _preferenceKey = 'rkl_theme';
  RklThemeId selected = RklThemeId.dark;

  Future<void> load() async {
    final preferences = await SharedPreferences.getInstance();
    final stored = preferences.getString(_preferenceKey);
    if (stored == null) return;
    selected = RklThemeId.values.firstWhere((theme) => theme.name == stored, orElse: () => RklThemeId.dark);
    notifyListeners();
  }

  Future<void> setTheme(RklThemeId theme) async {
    if (theme == selected) return;
    selected = theme;
    notifyListeners();
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(_preferenceKey, theme.name);
  }
}

class _RklThemeMarker extends ThemeExtension<_RklThemeMarker> {
  final RklThemeId id;
  const _RklThemeMarker(this.id);

  @override
  _RklThemeMarker copyWith({RklThemeId? id}) => _RklThemeMarker(id ?? this.id);

  @override
  _RklThemeMarker lerp(covariant _RklThemeMarker? other, double t) => other ?? this;
}

class _RklTokens extends ThemeExtension<_RklTokens> {
  final Color accent;
  final Color positive;
  final Color negative;
  final Color warning;
  final Color muted;
  final Color raised;

  const _RklTokens({required this.accent, required this.positive, required this.negative, required this.warning, required this.muted, required this.raised});

  @override
  _RklTokens copyWith({Color? accent, Color? positive, Color? negative, Color? warning, Color? muted, Color? raised}) => _RklTokens(
        accent: accent ?? this.accent,
        positive: positive ?? this.positive,
        negative: negative ?? this.negative,
        warning: warning ?? this.warning,
        muted: muted ?? this.muted,
        raised: raised ?? this.raised,
      );

  @override
  _RklTokens lerp(covariant _RklTokens? other, double t) => other ?? this;
}

ThemeData _themeFor(RklThemeId id) {
  final isLight = id == RklThemeId.light;
  final seed = id == RklThemeId.neon ? const Color(0xff38e8ff) : id == RklThemeId.pro ? const Color(0xff7ea6d8) : _mint;
  final background = isLight ? const Color(0xfff3f6f8) : id == RklThemeId.neon ? const Color(0xff060b12) : _ink;
  final surface = isLight ? Colors.white : id == RklThemeId.pro ? const Color(0xff101923) : id == RklThemeId.neon ? const Color(0xff0b1520) : _panel;
  final scheme = ColorScheme.fromSeed(seedColor: seed, brightness: isLight ? Brightness.light : Brightness.dark).copyWith(
    surface: surface,
    surfaceContainerHighest: isLight ? const Color(0xffe8eef2) : _panelRaised,
    outline: isLight ? const Color(0xffcbd5dc) : _line,
    onSurface: isLight ? const Color(0xff18232d) : Colors.white,
    onSurfaceVariant: isLight ? const Color(0xff52616d) : _muted,
  );
  final tokens = _RklTokens(
    accent: seed,
    positive: isLight ? const Color(0xff087443) : const Color(0xff55e0b2),
    negative: isLight ? const Color(0xffb42318) : const Color(0xffff6675),
    warning: isLight ? const Color(0xff9a6700) : _amber,
    muted: scheme.onSurfaceVariant,
    raised: scheme.surfaceContainerHighest,
  );
  return ThemeData(
    brightness: isLight ? Brightness.light : Brightness.dark,
    colorScheme: scheme,
    scaffoldBackgroundColor: background,
    useMaterial3: true,
    visualDensity: id == RklThemeId.pro ? VisualDensity.compact : VisualDensity.standard,
    cardTheme: CardThemeData(color: surface, margin: EdgeInsets.zero, elevation: isLight ? 1 : 0),
    appBarTheme: AppBarTheme(backgroundColor: background, surfaceTintColor: Colors.transparent, foregroundColor: scheme.onSurface),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: surface,
      indicatorColor: seed.withValues(alpha: .16),
      labelTextStyle: const WidgetStatePropertyAll(TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
    ),
    dividerTheme: DividerThemeData(color: scheme.outline.withValues(alpha: .6)),
    extensions: <ThemeExtension<dynamic>>[_RklThemeMarker(id), tokens],
  );
}

String _themeLabel(RklThemeId id) => switch (id) {
      RklThemeId.dark => 'RKL DARK',
      RklThemeId.light => 'RKL LIGHT',
      RklThemeId.pro => 'RKL PRO',
      RklThemeId.neon => 'RKL NEON',
    };

void main() => runApp(const RklApp());

class RklApp extends StatefulWidget {
  const RklApp({super.key});

  @override
  State<RklApp> createState() => _RklAppState();
}

class _RklAppState extends State<RklApp> {
  final themeController = RklThemeController();

  @override
  void initState() {
    super.initState();
    themeController.addListener(_themeChanged);
    themeController.load();
  }

  void _themeChanged() => setState(() {});

  @override
  void dispose() {
    themeController.removeListener(_themeChanged);
    themeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'RKL Control Centre',
      debugShowCheckedModeBanner: false,
      theme: _themeFor(themeController.selected),
      home: ControlCentre(onThemeChanged: themeController.setTheme),
    );
  }
}

class RklApi {
  final http.Client client = http.Client();

  Map<String, String> get _headers => {'Authorization': 'Bearer $apiToken', 'Accept': 'application/json'};

  Future<Map<String, dynamic>> get(String resource) async {
    final response = await client
        .get(Uri.parse('$apiBase/api/v1/mobile/$resource'), headers: _headers)
        .timeout(const Duration(seconds: 12));
    if (response.statusCode != 200) throw Exception('API ${response.statusCode}: ${response.reasonPhrase}');
    final decoded = jsonDecode(response.body);
    if (decoded is! Map) throw const FormatException('Expected an object response');
    return Map<String, dynamic>.from(decoded);
  }

  Future<Map<String, dynamic>> observerSnapshot() async {
    final response = await client
        .get(Uri.parse('$apiBase/api/v1/observer/snapshot'), headers: _headers)
        .timeout(const Duration(seconds: 12));
    if (response.statusCode != 200) throw Exception('Observer API ${response.statusCode}: ${response.reasonPhrase}');
    final decoded = jsonDecode(response.body);
    if (decoded is! Map || decoded['protocol'] != 'rkl.observer.v1') {
      throw const FormatException('Expected rkl.observer.v1 envelope');
    }
    final payload = decoded['payload'];
    if (payload is! Map) throw const FormatException('Expected observer payload');
    return Map<String, dynamic>.from(payload);
  }

  WebSocketChannel stream() {
    final apiUri = Uri.parse(apiWsBase.isEmpty ? apiBase : apiWsBase);
    final isLocalHost = apiUri.host == '127.0.0.1' || apiUri.host == 'localhost' || apiUri.host == '10.0.2.2';
    final socketUri = apiWsBase.isEmpty && isLocalHost && apiUri.hasPort
        ? apiUri.replace(port: apiUri.port + 1)
        : apiUri;
    final socketBase = socketUri.replace(scheme: socketUri.scheme == 'https' ? 'wss' : 'ws');
    return IOWebSocketChannel.connect(
      socketBase.replace(path: '${socketBase.path.replaceFirst(RegExp(r'/$'), '')}/api/v1/observer/stream'),
      protocols: const [],
      headers: {'Authorization': 'Bearer $apiToken'},
      connectTimeout: const Duration(seconds: 8),
    );
  }

  void dispose() => client.close();
}

class ControlCentre extends StatefulWidget {
  final ValueChanged<RklThemeId>? onThemeChanged;

  const ControlCentre({super.key, this.onThemeChanged});

  @override
  State<ControlCentre> createState() => _ControlCentreState();
}

class _ControlCentreState extends State<ControlCentre> {
  final RklApi api = RklApi();
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  Timer? refreshTimer;
  Timer? reconnectTimer;
  WebSocketChannel? socket;
  StreamSubscription? socketSubscription;
  int tab = 0;
  bool loading = true;
  bool refreshing = false;
  bool streamConnected = false;
  Map<String, dynamic> status = {};
  Map<String, dynamic> market = {};
  Map<String, dynamic> signals = {};
  Map<String, dynamic> orders = {};
  Map<String, dynamic> positions = {};
  Map<String, dynamic> options = {};
  Map<String, dynamic> fills = {};
  Map<String, dynamic> exits = {};
  Map<String, dynamic> notifications = {};
  Map<String, dynamic> reports = {};
  Map<String, dynamic> canonical = {};
  Object? error;
  DateTime? updatedAt;
  int? lastSequence;

  static const _titles = [
    'Control Centre', 'Market', 'Index Data', 'Indicators', 'Options', 'Signals',
    'Notifications', 'Orders', 'Fills', 'Positions', 'Exits', 'Reports', 'Sandbox', 'System Health', 'Settings',
  ];
  static const _bottomTabs = [0, 1, 5, 7, 9];
  static const _icons = [Icons.dashboard_outlined, Icons.show_chart_rounded, Icons.table_chart_outlined, Icons.insights_outlined, Icons.grid_view_rounded, Icons.bolt_outlined, Icons.notifications_none_rounded, Icons.receipt_long_outlined, Icons.data_object_rounded, Icons.account_balance_wallet_outlined, Icons.exit_to_app_rounded, Icons.assessment_outlined, Icons.science_outlined, Icons.health_and_safety_outlined, Icons.settings_outlined];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      refresh();
      connectStream();
      refreshTimer = Timer.periodic(const Duration(seconds: 10), (_) => refresh());
    });
  }

  @override
  void dispose() {
    refreshTimer?.cancel();
    reconnectTimer?.cancel();
    socketSubscription?.cancel();
    socket?.sink.close();
    api.dispose();
    super.dispose();
  }

  Future<void> refresh() async {
    if (refreshing) return;
    refreshing = true;
    try {
      final payload = await api.observerSnapshot();
      if (!mounted) return;
      setState(() {
        _applyCanonical(payload);
        error = null; loading = false; updatedAt = DateTime.now();
      });
    } catch (exception) {
      if (mounted) setState(() { error = exception; loading = false; });
    } finally {
      refreshing = false;
    }
  }

  void connectStream() {
    reconnectTimer?.cancel();
    socketSubscription?.cancel();
    try {
      socket?.sink.close();
      final channel = api.stream();
      socket = channel;
      channel.ready.catchError((_) => _streamEnded());
      socketSubscription = channel.stream.listen(_onStreamMessage, onError: (_) => _streamEnded(), onDone: _streamEnded);
    } catch (_) {
      _streamEnded();
    }
  }

  void _onStreamMessage(dynamic message) {
    try {
      final decoded = jsonDecode(message as String);
      if (decoded is! Map) return;
      final envelope = Map<String, dynamic>.from(decoded);
      if (envelope['protocol'] != 'rkl.observer.v1') return;
      if (envelope['event_type'] == 'WELCOME' || envelope['event_type'] == 'HEARTBEAT') return;
      final sequence = envelope['sequence'] as int?;
      if (sequence != null && lastSequence != null && sequence != lastSequence! + 1) {
        lastSequence = null;
        refresh();
        return;
      }
      lastSequence = sequence ?? lastSequence;
      final payload = envelope['payload'];
      if (!mounted || payload is! Map) return;
      setState(() {
        _applyCanonical(Map<String, dynamic>.from(payload));
        streamConnected = true;
        updatedAt = DateTime.now(); error = null;
      });
    } catch (_) {
      // A malformed event should not take down the read-only display.
    }
  }

  void _applyCanonical(Map<String, dynamic> payload) {
    canonical = payload;
    final health = _map(payload['SystemHealth']);
    final marketStatus = _map(payload['MarketStatus']);
    final indexState = _map(payload['IndexState']);
    final indicatorState = _map(payload['IndicatorState']);
    final optionUniverse = _list(payload['OptionUniverse']);
    status = {
      'system_status': health['status'], 'execution_mode': health['execution_mode'],
      'components': _map(health['components']), 'ws_status': health['ws_status'],
      'startup_phase': health['startup_phase'], 'last_event': health['last_event'],
      'reconnects': health['reconnects'], 'market_status': marketStatus['market_state'],
    };
    market = {'instrument_names': indexState.keys.toList(), 'IndexState': indexState, 'MarketStatus': marketStatus, 'market_status': marketStatus['market_state'], 'indicators': indicatorState};
    signals = {'signal': payload['SignalState'], 'signal_history': const [], 'signal_queue': const []};
    orders = {'orders': _list(payload['OrderState'])};
    fills = {'fills': _list(payload['FillState'])};
    positions = {'position_details': _list(payload['PositionState'])};
    exits = {'exits': _list(payload['ExitState'])};
    options = {'option_universe': {for (var index = 0; index < optionUniverse.length; index++) '$index': optionUniverse[index]}};
    notifications = {'events': _list(payload['IncidentState'])};
    reports = {'reports': payload['ReportSummary'] == null ? const [] : [payload['ReportSummary']]};
  }

  void _streamEnded() {
    if (!mounted) return;
    if (streamConnected) setState(() => streamConnected = false);
    if (reconnectTimer != null) return;
    reconnectTimer = Timer(const Duration(seconds: 8), () {
      reconnectTimer = null;
      connectStream();
    });
  }

  int get _bottomIndex {
    final index = _bottomTabs.indexOf(tab);
    return index < 0 ? 0 : index;
  }

  void _selectTab(int value) {
    if (value < 0 || value >= _titles.length) return;
    setState(() => tab = value);
    Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      key: _scaffoldKey,
      drawer: _drawer(),
      appBar: AppBar(
        leading: IconButton(onPressed: () => _scaffoldKey.currentState?.openDrawer(), icon: const Icon(Icons.menu_rounded)),
        title: Text(_titles[tab], style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800, letterSpacing: .2)),
        actions: [
          _LivePill(connected: streamConnected, compact: true),
          IconButton(onPressed: loading ? null : refresh, icon: const Icon(Icons.refresh_rounded)),
          const SizedBox(width: 6),
        ],
      ),
      body: SafeArea(child: _body()),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _bottomIndex,
        onDestinationSelected: (index) => _selectTab(_bottomTabs[index]),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard_outlined), selectedIcon: Icon(Icons.dashboard), label: 'Control'),
          NavigationDestination(icon: Icon(Icons.show_chart_rounded), label: 'Market'),
          NavigationDestination(icon: Icon(Icons.bolt_outlined), selectedIcon: Icon(Icons.bolt), label: 'Signals'),
          NavigationDestination(icon: Icon(Icons.receipt_long_outlined), selectedIcon: Icon(Icons.receipt_long), label: 'Orders'),
          NavigationDestination(icon: Icon(Icons.account_balance_wallet_outlined), label: 'Positions'),
        ],
      ),
    );
  }

  Widget _body() {
    if (loading) return const _LoadingView();
    switch (tab) {
      case 0: return _controlCentre();
      case 1: return _marketPage();
      case 2: return _indexPage();
      case 3: return _indicatorPage();
      case 4: return _optionsPage();
      case 5: return _listPage('Signals', signals['signal_history'], Icons.bolt_rounded);
      case 6: return _listPage('Notifications', notifications['events'], Icons.notifications_none_rounded);
      case 7: return _listPage('Orders', orders['orders'], Icons.receipt_long_rounded);
      case 8: return _listPage('Fills', fills['fills'], Icons.data_object_rounded);
      case 9: return _listPage('Positions', positions['position_details'], Icons.account_balance_wallet_outlined);
      case 10: return _listPage('Exits', exits['exits'], Icons.exit_to_app_rounded);
      case 11: return _listPage('Reports', reports['reports'], Icons.assessment_outlined);
      case 12: return _emptyPage('Sandbox', 'NO SANDBOX DATA', 'The read-only client has no sandbox execution surface.');
      case 13: return _healthPage();
      case 14: return _settingsPage();
      default: return _controlCentre();
    }
  }

  Widget _controlCentre() {
    final components = _map(status['components']);
    final activeSignals = _list(signals['signal_queue']).isNotEmpty ? _list(signals['signal_queue']) : _list(signals['signal_history']);
    final activePositions = _list(positions['position_details']);
    return _scroll(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _heroHeader(),
      if (error != null) _AlertBanner(title: 'Backend unavailable', detail: error.toString(), color: Colors.redAccent),
      _section('ENGINE SNAPSHOT', trailing: const _ReadOnlyBadge()),
      _cardGrid([
        _MetricCard('ENGINE', status['system_status'], Icons.memory_rounded, _statusColor(status['system_status'])),
        _MetricCard('MARKET', status['market_status'], Icons.access_time_rounded, _statusColor(status['market_status'])),
        _MetricCard('FEED', streamConnected ? 'CONNECTED' : 'OFFLINE', Icons.wifi_tethering_rounded, streamConnected ? _mint : Colors.redAccent),
        _MetricCard('HEARTBEAT', _timeLabel(updatedAt), Icons.favorite_outline_rounded, _blue),
      ]),
      const SizedBox(height: 18),
      _section('INDEX MONITOR', trailing: _SmallText('${_list(market['instrument_names']).length} instruments')),
      _indexCards(),
      const SizedBox(height: 18),
      _section('ACTIVITY', trailing: _SmallText('${activeSignals.length} signals  /  ${activePositions.length} positions')),
      _activitySummary(activeSignals, activePositions),
      const SizedBox(height: 18),
      _section('SYSTEM COMPONENTS'),
      _componentStrip(components),
      const SizedBox(height: 18),
      _section('RECENT EVENTS'),
      _recentEvents(),
      const SizedBox(height: 8),
    ]));
  }

  Widget _heroHeader() => Builder(builder: (context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
        width: double.infinity,
        padding: const EdgeInsets.fromLTRB(18, 20, 18, 18),
        decoration: BoxDecoration(
          gradient: LinearGradient(colors: [colors.surfaceContainerHighest, colors.surface], begin: Alignment.topLeft, end: Alignment.bottomRight),
          border: Border.all(color: colors.outline), borderRadius: BorderRadius.circular(16),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Container(width: 10, height: 10, decoration: const BoxDecoration(color: _mint, shape: BoxShape.circle)),
            const SizedBox(width: 9), const Text('RKL CONTROL CENTRE', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w900, letterSpacing: 1.5)),
            const Spacer(), const _ReadOnlyBadge(),
          ]),
          const SizedBox(height: 14),
          const Text('Authoritative engine state', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800, letterSpacing: -.3)),
          const SizedBox(height: 5),
          Text('${status['execution_mode'] ?? 'READ_ONLY'}  ·  ${status['startup_phase'] ?? 'STARTUP'}', style: const TextStyle(color: _muted, fontSize: 13)),
          const SizedBox(height: 16),
          Row(children: [
            _HeaderStat('LAST UPDATE', _timeLabel(updatedAt)),
            const SizedBox(width: 24), _HeaderStat('SEQUENCE', '${lastSequence ?? '--'}'),
          ]),
        ]),
      );
  });

  Widget _marketPage() => _scroll(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _pageIntro('Market', 'Authoritative index state and data freshness.'),
        _marketStatusCard(),
        _indexCards(compact: false),
      ]));

  Widget _marketStatusCard() {
    final marketStatus = _displayStatus(market['market_status']);
    final feedStatus = _displayStatus(status['ws_status'] ?? market['sync']);
    final healthStatus = _displayStatus(market['health']);
    return Padding(padding: const EdgeInsets.only(bottom: 16), child: _TerminalCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [const Icon(Icons.access_time_rounded, size: 18), const SizedBox(width: 8), Text(marketStatus, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900)), const Spacer(), _StateBadge(marketStatus)]),
      const SizedBox(height: 14),
      Row(children: [Expanded(child: _StatusPair('FEED', feedStatus)), Expanded(child: _StatusPair('DATA', healthStatus)), Expanded(child: _StatusPair('LAST UPDATE', _timeLabel(updatedAt)))]),
    ])));
  }

  Widget _indexPage() => _scroll(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _pageIntro('Index Data', 'Current instruments, last price and candle context.'), _indexCards(compact: false),
      ]));

  Widget _indicatorPage() {
    final indicators = _map(market['indicators']);
    return _scroll(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _pageIntro('Indicators', 'Backend-calculated values from completed candles.'),
      if (indicators.isEmpty) _emptyState('NO INDICATOR DATA', 'Waiting for completed market candles.')
      else ...indicators.entries.map((entry) => _indicatorCard(entry.key, entry.value)),
    ]));
  }

  Widget _optionsPage() {
    final universe = _map(options['option_universe']);
    return _scroll(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _pageIntro('Options', 'Read-only option universe published by the engine.'),
      if (universe.isEmpty) _emptyState('NO OPTION DATA', 'The backend has not published an option universe.')
      else ...universe.entries.take(40).map((entry) => _dataCard(entry.key.toString(), entry.value)),
    ]));
  }

  Widget _healthPage() {
    final components = _map(status['components']);
    return _scroll(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _pageIntro('System Health', 'Component readiness reported by the RKL engine.'),
      _componentList(components),
      const SizedBox(height: 18), _section('TRANSPORT'), _keyValueCard({'WebSocket': streamConnected ? 'CONNECTED' : 'DISCONNECTED', 'Last event': status['last_event'], 'Reconnects': status['reconnects']}),
    ]));
  }

  Widget _settingsPage() => _scroll(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _pageIntro('Settings', 'Connection, theme, and client posture.'),
        _keyValueCard({'Mode': 'READ-ONLY', 'API base': apiBase, 'Authentication': apiToken.isEmpty ? 'TOKEN NOT SET' : 'BEARER TOKEN SET', 'Writes': 'DISABLED'}),
        const SizedBox(height: 18),
        _section('APPEARANCE'),
        _ThemeSelector(onChanged: widget.onThemeChanged),
        const SizedBox(height: 18),
        const _AlertBanner(title: 'No control surface', detail: 'Orders, system controls and broker credentials are never exposed by this client.', color: _blue),
      ]));

  Widget _listPage(String title, Object? data, IconData icon) {
    final items = _list(data);
    return _scroll(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _pageIntro(title, 'Authoritative read-only records from the RKL service.'),
      if (items.isEmpty) _emptyState('NO ${title.toUpperCase()} DATA', 'Waiting for backend events.')
      else ...items.reversed.take(40).map((item) => _recordCard(item, icon, title)),
    ]));
  }

  Widget _emptyPage(String title, String headline, String detail) => _scroll(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_pageIntro(title, detail), _emptyState(headline, detail)]));

  Widget _indexCards({bool compact = true}) {
    final instrumentNames = _list(market['instrument_names']);
    final names = instrumentNames.isEmpty ? ['NIFTY', 'BANKNIFTY', 'SENSEX', 'MIDCPNIFTY'] : instrumentNames;
    final indexState = _map(market['IndexState']);
    return Column(children: names.map((rawName) {
      final name = rawName.toString();
      final index = _map(indexState[name]);
      final tick = <String, dynamic>{
        'ltp': index['ltp'], 'timestamp': index['timestamp'],
        'exchange_timestamp': index['exchange_timestamp'],
        'received_timestamp': index['received_timestamp'], 'source': index['source'],
        'previous_candle': index['previous_candle'],
      };
      final candle = _map(index['current_candle']);
      const change = null;
      return Padding(padding: const EdgeInsets.only(bottom: 8), child: _IndexCard(name: name, tick: tick, candle: candle, change: change, compact: compact, marketStatus: market['market_status']));
    }).toList());
  }

  Widget _indicatorCard(String name, Object? value) {
    final data = _map(value);
    return Padding(padding: const EdgeInsets.only(bottom: 10), child: _TerminalCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(name, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15)), const SizedBox(height: 12),
      Row(children: [_ValueChip('RSI14', data['rsi14']), _ValueChip('RSI14 SMA', data['rsi_sma5']), _ValueChip('CCI5', data['cci5'])]),
    ])));
  }

  Widget _activitySummary(List<dynamic> signalItems, List<dynamic> positionItems) => Row(children: [
        Expanded(child: _CountCard('ACTIVE SIGNALS', signalItems.length, Icons.bolt_rounded, _amber)),
        const SizedBox(width: 10), Expanded(child: _CountCard('POSITIONS', positionItems.length, Icons.account_balance_wallet_outlined, _blue)),
        const SizedBox(width: 10), Expanded(child: _CountCard('P&L', _pnl(), Icons.show_chart_rounded, _pnlColor())),
      ]);

  Widget _componentStrip(Map<String, dynamic> components) => SizedBox(height: 74, child: ListView(scrollDirection: Axis.horizontal, children: components.entries.take(8).map((entry) => _StatusTile(entry.key, entry.value)).toList()));

  Widget _componentList(Map<String, dynamic> components) => Column(children: components.entries.map((entry) => Padding(padding: const EdgeInsets.only(bottom: 8), child: _TerminalCard(child: Row(children: [Icon(Icons.circle, size: 9, color: _statusColor(entry.value)), const SizedBox(width: 12), Expanded(child: Text(entry.key, style: const TextStyle(fontWeight: FontWeight.w700))), Text(_displayStatus(entry.value), style: TextStyle(color: _statusColor(entry.value), fontWeight: FontWeight.w800))])))).toList());

  Widget _recentEvents() {
    final events = _list(notifications['events']);
    if (events.isEmpty) return _emptyState('NO RECENT EVENTS', 'No notification events have been published.');
    return Column(children: events.reversed.take(4).map((event) => _recordCard(event, Icons.notifications_none_rounded, 'Event')).toList());
  }

  Widget _recordCard(Object? item, IconData icon, String title) {
    final data = _map(item);
    final heading = data['signal_type'] ?? data['event_type'] ?? data['status'] ?? data['order_id'] ?? title;
    final detail = _compactFields(data, const ['symbol', 'instrument', 'side', 'quantity', 'price', 'reason', 'severity', 'timestamp', 'event_time', 'status']);
    return Padding(padding: const EdgeInsets.only(bottom: 8), child: _TerminalCard(child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(icon, color: _blue, size: 20), const SizedBox(width: 12), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('$heading', style: const TextStyle(fontWeight: FontWeight.w800)), const SizedBox(height: 5), Text(detail.isEmpty ? 'NO DETAILS AVAILABLE' : detail, style: const TextStyle(color: _muted, fontSize: 12, height: 1.4))]))])));
  }

  Widget _dataCard(String title, Object? value) {
    final data = _map(value);
    final summary = data.isEmpty ? _displayValue(value) : _compactFields(data, const ['instrument', 'underlying', 'strike', 'expiry', 'option_type', 'ltp', 'status']);
    return Padding(padding: const EdgeInsets.only(bottom: 8), child: _TerminalCard(child: Row(children: [Expanded(child: Text(title, style: const TextStyle(fontWeight: FontWeight.w800))), const SizedBox(width: 12), Expanded(child: Text(summary, textAlign: TextAlign.right, maxLines: 3, overflow: TextOverflow.ellipsis, style: const TextStyle(color: _muted, fontSize: 12)))])));
  }

  Widget _keyValueCard(Map<String, dynamic> values) => _TerminalCard(child: Column(children: values.entries.map((entry) => Padding(padding: const EdgeInsets.symmetric(vertical: 7), child: Row(children: [Expanded(child: Text(entry.key, style: const TextStyle(color: _muted))), Flexible(child: Text(_displayValue(entry.value), textAlign: TextAlign.right, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700)))]))).toList()));

  Widget _drawer() => Drawer(backgroundColor: Theme.of(context).colorScheme.surface, child: SafeArea(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.fromLTRB(20, 20, 20, 16), child: Row(children: [Container(width: 10, height: 10, decoration: const BoxDecoration(color: _mint, shape: BoxShape.circle)), const SizedBox(width: 10), const Text('RKL / MOBILE', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 1.3)), const Spacer(), const _ReadOnlyBadge()])),
        const Divider(color: _line, height: 1),
        Expanded(child: ListView.builder(itemCount: _titles.length, itemBuilder: (context, index) => ListTile(leading: Icon(_icons[index], size: 20, color: tab == index ? _mint : _muted), title: Text(_titles[index], style: TextStyle(fontSize: 13, fontWeight: tab == index ? FontWeight.w800 : FontWeight.w500)), selected: tab == index, selectedTileColor: _mint.withValues(alpha: .08), onTap: () => _selectTab(index)))),
      ])));

  Widget _scroll(Widget child) => RefreshIndicator(color: _mint, onRefresh: refresh, child: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [child]));
  Widget _pageIntro(String title, String detail) => Padding(padding: const EdgeInsets.only(bottom: 18, top: 6), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title.toUpperCase(), style: const TextStyle(color: _mint, fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: 1.6)), const SizedBox(height: 7), Text(detail, style: const TextStyle(color: _muted, fontSize: 13))]));
  Widget _section(String title, {Widget? trailing}) => Padding(padding: const EdgeInsets.only(bottom: 10), child: Row(children: [Text(title, style: const TextStyle(color: _muted, fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: 1.4)), const Spacer(), if (trailing != null) trailing]));
  Widget _cardGrid(List<Widget> children) => GridView.count(shrinkWrap: true, physics: const NeverScrollableScrollPhysics(), crossAxisCount: 2, childAspectRatio: 1.55, crossAxisSpacing: 10, mainAxisSpacing: 10, children: children);
  Widget _emptyState(String title, String detail) => _TerminalCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [const Icon(Icons.hourglass_empty_rounded, color: _muted), const SizedBox(height: 12), Text(title, style: const TextStyle(fontWeight: FontWeight.w900, letterSpacing: .7)), const SizedBox(height: 5), Text(detail, style: const TextStyle(color: _muted, fontSize: 13))]));
  Widget _pnl() => Text(_number(_findPnl()), style: TextStyle(color: _pnlColor(), fontWeight: FontWeight.w900, fontSize: 16));
  Color _pnlColor() => _findPnl() is num && (_findPnl() as num) < 0 ? Colors.redAccent : _mint;
  Object? _findPnl() { for (final key in ['pnl', 'p_and_l', 'realized_pnl']) { if (positions[key] != null) return positions[key]; } return null; }
}

class _TerminalCard extends StatelessWidget {
  final Widget child;
  const _TerminalCard({required this.child});
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(width: double.infinity, padding: const EdgeInsets.all(14), decoration: BoxDecoration(color: colors.surface, border: Border.all(color: colors.outline), borderRadius: BorderRadius.circular(13)), child: child);
  }
}

class _ThemeSelector extends StatelessWidget {
  final ValueChanged<RklThemeId>? onChanged;
  const _ThemeSelector({required this.onChanged});

  @override
  Widget build(BuildContext context) {
    final selected = _themeFromBrightness(context);
    return _TerminalCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(_themeLabel(selected), style: const TextStyle(fontWeight: FontWeight.w900)),
      const SizedBox(height: 10),
      DropdownButtonFormField<RklThemeId>(
        initialValue: selected,
        decoration: const InputDecoration(labelText: 'Terminal theme', border: OutlineInputBorder()),
        items: RklThemeId.values.map((theme) => DropdownMenuItem(value: theme, child: Text(_themeLabel(theme)))).toList(),
        onChanged: onChanged == null ? null : (theme) { if (theme != null) onChanged!(theme); },
      ),
    ]));
  }

  RklThemeId _themeFromBrightness(BuildContext context) {
    return Theme.of(context).extension<_RklThemeMarker>()?.id ?? RklThemeId.dark;
  }
}

class _StatusPair extends StatelessWidget {
  final String label;
  final String value;
  const _StatusPair(this.label, this.value);

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(color: _muted, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: .8)),
        const SizedBox(height: 4),
        Text(value, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: _statusColor(value), fontSize: 11, fontWeight: FontWeight.w900)),
      ]);
}

class _StateBadge extends StatelessWidget {
  final String state;
  const _StateBadge(this.state);

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        decoration: BoxDecoration(color: _statusColor(state).withValues(alpha: .12), borderRadius: BorderRadius.circular(6)),
        child: Text(state, style: TextStyle(color: _statusColor(state), fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: .6)),
      );
}

class _IndexCard extends StatelessWidget {
  final String name;
  final Map<String, dynamic> tick;
  final Map<String, dynamic> candle;
  final Object? change;
  final bool compact;
  final Object? marketStatus;
  const _IndexCard({required this.name, required this.tick, required this.candle, required this.change, required this.compact, required this.marketStatus});
  @override
  Widget build(BuildContext context) {
    final positive = change is num ? (change as num) >= 0 : null;
    final freshness = _freshnessLabel(marketStatus, tick['timestamp'] ?? candle['timestamp']);
    return _TerminalCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Text(name, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15)), const Spacer(), _StateBadge(freshness)]),
      const SizedBox(height: 8),
      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [Text(_number(tick['ltp']), style: const TextStyle(fontSize: 25, fontWeight: FontWeight.w900, letterSpacing: -.5)), const SizedBox(width: 10), if (change != null) Text(_number(change, signed: true), style: TextStyle(color: positive == true ? _mint : positive == false ? Colors.redAccent : _muted, fontWeight: FontWeight.w800))]),
      const SizedBox(height: 9),
      Wrap(spacing: 8, runSpacing: 6, children: [_ContextChip('CURRENT 5 MIN', candle['close']), _ContextChip('LAST CLOSED 5 MIN', _map(_map(tick['previous_candle']))['close']), _ContextChip('RSI14', tick['rsi14']), _ContextChip('CCI5', tick['cci5'])]),
      if (!compact) ...[const SizedBox(height: 10), Text('SMA: ${tick['sma'] ?? tick['sma_info'] ?? 'UNKNOWN'}', style: const TextStyle(color: _muted, fontSize: 12))],
    ]));
  }
}

class _MetricCard extends StatelessWidget {
  final String label; final Object? value; final IconData icon; final Color color;
  const _MetricCard(this.label, this.value, this.icon, this.color);
  @override
  Widget build(BuildContext context) => _TerminalCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(icon, color: color, size: 18), const Spacer(), Text(label, style: const TextStyle(color: _muted, fontSize: 10, fontWeight: FontWeight.w800, letterSpacing: 1)), const SizedBox(height: 4), Text('${value ?? 'UNKNOWN'}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: color, fontWeight: FontWeight.w900, fontSize: 14))]));
}

class _CountCard extends StatelessWidget {
  final String label; final Object value; final IconData icon; final Color color;
  const _CountCard(this.label, this.value, this.icon, this.color);
  @override
  Widget build(BuildContext context) => _TerminalCard(child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(icon, size: 18, color: color), const SizedBox(height: 14), Text(label, style: const TextStyle(color: _muted, fontSize: 9, fontWeight: FontWeight.w800)), const SizedBox(height: 4), value is Widget ? value as Widget : Text('$value', style: TextStyle(color: color, fontSize: 17, fontWeight: FontWeight.w900))]));
}

class _StatusTile extends StatelessWidget {
  final String label; final Object? value;
  const _StatusTile(this.label, this.value);
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
        width: 116,
        margin: const EdgeInsets.only(right: 8),
        padding: const EdgeInsets.all(11),
        decoration: BoxDecoration(color: colors.surface, border: Border.all(color: colors.outline), borderRadius: BorderRadius.circular(11)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [
          Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: _muted, fontSize: 10, fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          Row(children: [
            Icon(Icons.circle, size: 8, color: _statusColor(value)),
            const SizedBox(width: 6),
            Expanded(child: Text('${value ?? 'UNKNOWN'}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: _statusColor(value), fontSize: 11, fontWeight: FontWeight.w900))),
          ]),
        ]),
        );
      }
}

class _ContextChip extends StatelessWidget {
  final String label; final Object? value;
  const _ContextChip(this.label, this.value);
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5), decoration: BoxDecoration(color: colors.surfaceContainerHighest, borderRadius: BorderRadius.circular(7)), child: Text('$label  ${_number(value)}', style: TextStyle(color: colors.onSurfaceVariant, fontSize: 10, fontWeight: FontWeight.w700)));
  }
}

class _ValueChip extends StatelessWidget {
  final String label; final Object? value;
  const _ValueChip(this.label, this.value);
  @override
  Widget build(BuildContext context) => Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label, style: const TextStyle(color: _muted, fontSize: 10)), const SizedBox(height: 4), Text(_number(value), style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15))]));
}

class _ReadOnlyBadge extends StatelessWidget {
  const _ReadOnlyBadge();
  @override
  Widget build(BuildContext context) => Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5), decoration: BoxDecoration(color: _blue.withValues(alpha: .12), border: Border.all(color: _blue.withValues(alpha: .4)), borderRadius: BorderRadius.circular(6)), child: const Text('READ-ONLY', style: TextStyle(color: _blue, fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: .7)));
}

class _LivePill extends StatelessWidget {
  final bool connected; final bool compact;
  const _LivePill({required this.connected, this.compact = false});
  @override
  Widget build(BuildContext context) => Container(margin: EdgeInsets.only(right: compact ? 0 : 8), padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5), decoration: BoxDecoration(color: (connected ? _mint : Colors.redAccent).withValues(alpha: .12), borderRadius: BorderRadius.circular(6)), child: Row(mainAxisSize: MainAxisSize.min, children: [Icon(Icons.circle, size: 7, color: connected ? _mint : Colors.redAccent), if (!compact) ...[const SizedBox(width: 5), Text(connected ? 'LIVE' : 'OFFLINE', style: TextStyle(color: connected ? _mint : Colors.redAccent, fontSize: 9, fontWeight: FontWeight.w900))]]));
}

class _AlertBanner extends StatelessWidget {
  final String title; final String detail; final Color color;
  const _AlertBanner({required this.title, required this.detail, required this.color});
  @override
  Widget build(BuildContext context) => Padding(padding: const EdgeInsets.only(bottom: 16), child: Container(width: double.infinity, padding: const EdgeInsets.all(13), decoration: BoxDecoration(color: color.withValues(alpha: .08), border: Border.all(color: color.withValues(alpha: .35)), borderRadius: BorderRadius.circular(12)), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(Icons.info_outline_rounded, color: color, size: 19), const SizedBox(width: 10), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: TextStyle(color: color, fontWeight: FontWeight.w900)), const SizedBox(height: 3), Text(detail, style: const TextStyle(color: _muted, fontSize: 12))]))])));
}

class _HeaderStat extends StatelessWidget {
  final String label; final String value;
  const _HeaderStat(this.label, this.value);
  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label, style: const TextStyle(color: _muted, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: .8)), const SizedBox(height: 4), Text(value, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 12))]);
}

class _SmallText extends StatelessWidget {
  final String text;
  const _SmallText(this.text);
  @override
  Widget build(BuildContext context) => Text(text, style: const TextStyle(color: _muted, fontSize: 11));
}

class _LoadingView extends StatelessWidget {
  const _LoadingView();
  @override
  Widget build(BuildContext context) => const Center(child: Column(mainAxisSize: MainAxisSize.min, children: [CircularProgressIndicator(color: _mint), SizedBox(height: 14), Text('SYNCING AUTHORITATIVE STATE', style: TextStyle(color: _muted, fontSize: 11, fontWeight: FontWeight.w800, letterSpacing: 1.2))]));
}

Map<String, dynamic> _map(Object? value) => value is Map ? Map<String, dynamic>.from(value) : <String, dynamic>{};
List<dynamic> _list(Object? value) => value is List ? List<dynamic>.from(value) : <dynamic>[];
String _number(Object? value, {bool signed = false}) {
  if (value == null) return 'UNKNOWN';
  if (value is num) return '${signed && value >= 0 ? '+' : ''}${value.toStringAsFixed(value is int ? 0 : 2)}';
  return value.toString();
}
String _displayValue(Object? value) {
  if (value == null) return 'UNKNOWN';
  if (value is num) return _number(value);
  if (value is String || value is bool) return value.toString();
  return 'NOT AVAILABLE';
}

String _compactFields(Map<String, dynamic> data, List<String> keys) {
  return keys.where(data.containsKey).map((key) => '$key: ${_displayValue(data[key])}').join('  ·  ');
}

String _timeLabel(DateTime? time) => time == null ? 'UNKNOWN' : '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}:${time.second.toString().padLeft(2, '0')}';
String _displayStatus(Object? value) {
  final text = '${value ?? ''}'.trim();
  if (text.isEmpty) return 'UNKNOWN';
  final upper = text.toUpperCase();
  if (upper.contains('CLOSED')) return 'MARKET CLOSED';
  if (upper.contains('STALE')) return 'STALE';
  if (upper.contains('READY')) return 'READY';
  if (upper.contains('CONNECTED')) return 'CONNECTED';
  if (upper.contains('OPEN')) return 'OPEN';
  if (upper.contains('OFFLINE') || upper.contains('DISCONNECTED')) return 'OFFLINE';
  return text;
}

String _freshnessLabel(Object? marketStatus, Object? timestamp) {
  final state = _displayStatus(marketStatus).toUpperCase();
  if (state.contains('CLOSED') || state.contains('STALE')) return 'LAST KNOWN';
  if (timestamp == null) return 'NO DATA';
  if (state.contains('OPEN') || state.contains('CONNECTED')) return 'LIVE';
  return 'UNKNOWN';
}

Color _statusColor(Object? value) {
  final text = _displayStatus(value).toUpperCase();
  if (text.contains('READY') || text.contains('OPEN') || text.contains('CONNECTED') || text.contains('LIVE')) return _mint;
  if (text.contains('ERROR') || text.contains('FAIL') || text.contains('OFFLINE') || text.contains('BLOCKED')) return Colors.redAccent;
  if (text.contains('WAIT') || text.contains('CLOSED') || text.contains('UNKNOWN')) return _amber;
  return _muted;
}
