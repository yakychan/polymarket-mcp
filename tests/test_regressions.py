import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from py_clob_client_v2.exceptions import PolyApiException

from polymarket_mcp.config import TradingError, decimal
from polymarket_mcp.engine import Engine
from polymarket_mcp.feed import ChainlinkFeed
from polymarket_mcp.insights import Insights
from polymarket_mcp.live import LiveBroker
from polymarket_mcp.monitor import ProcessLock, Monitor
from polymarket_mcp.server import create_server
from polymarket_mcp.stops import Stops
from scripts.backup_db import backup
from scripts.build_share import build, package_files, ROOT
from test_trading import engine, quote, live_engine, FakePublic


@pytest.mark.parametrize('status,message,expected', [
    (400, 'FOK orders are filled or killed', 'rejected'),
    (400, 'not enough balance / allowance', 'rejected'),
    (400, 'duplicate order', 'unknown'),
    (500, 'upstream error', 'unknown'),
])
def test_sdk_rejection_classification(engine, status, message, expected):
    live = live_engine(engine)
    broker = object.__new__(LiveBroker)
    def post(*a):
        raise PolyApiException(httpx.Response(status, json={'error': message}))
    broker.client = SimpleNamespace(post_order=post)
    live.broker.submit = broker.submit
    receipt = live.execute(quote(live), 'Fixture rejection')
    assert receipt['status'] == expected
    if expected == 'rejected':
        assert live.execute(quote(live), 'Next allowed')['status'] == 'rejected'
    else:
        with pytest.raises(TradingError, match='incierta'):
            live.execute(quote(live), 'Still blocked')


def test_order_404_still_queries_trades_and_preserves_evidence(engine):
    live = live_engine(engine)
    live.execute(quote(live), 'Entry')
    queried = []
    broker = object.__new__(LiveBroker)
    def missing(order_id):
        raise PolyApiException(httpx.Response(404, json={'error': 'not found'}))
    def trades(*a):
        queried.append(True)
        return [{'id': 'fill', 'taker_order_id': '0xorder', 'asset_id': '1', 'side': 'BUY',
                 'market': 'condition', 'status': 'CONFIRMED', 'size': '10', 'price': '0.50'}]
    broker.client = SimpleNamespace(get_order=missing, get_trades=trades)
    live.broker.reconcile = broker.reconcile
    live.sync_orders()
    order = live.history()['orders'][0]
    assert queried and order['execution']['shares'] == '10'
    assert order['status'] == 'unknown'  # no proof of complete trade coverage yet


@pytest.mark.parametrize('statuses,expected,shares', [
    (['FAILED', 'FAILED'], 'failed', None),
    (['FAILED', 'CONFIRMED'], 'partially_confirmed', '5'),
    (['CONFIRMED', 'CONFIRMED'], 'confirmed', '10'),
    (['MATCHED', 'CONFIRMED'], 'submitted', '5'),
])
def test_fill_finality_and_partial_accounting(engine, statuses, expected, shares):
    live = live_engine(engine)
    live.execute(quote(live), 'Entry')
    def reconcile(order_id, condition):
        return ({'id': order_id, 'asset_id': '1', 'side': 'BUY', 'status': 'MATCHED', 'size_matched': '10'},
                [{'id': str(i), 'size': '5', 'price': '0.50', 'status': state} for i, state in enumerate(statuses)])
    live.broker.reconcile = reconcile
    live.sync_orders()
    order = live.history()['orders'][0]
    assert order['status'] == expected
    assert (order['execution']['shares'] if order['execution'] else None) == shares
    before = len(live.movements()['events'])
    live.sync_orders()
    assert len(live.movements()['events']) == before


def test_duplicate_fill_not_counted_twice(engine):
    live = live_engine(engine)
    live.execute(quote(live), 'Entry')
    original = live.broker.reconcile
    live.broker.confirm = True
    def duplicated(*a):
        remote, fills = original(*a)
        return remote, fills + fills
    live.broker.reconcile = duplicated
    live.sync_orders()
    assert live.history()['orders'][0]['execution']['shares'] == '10'


def test_market_read_does_not_hold_sqlite_write_lock(engine):
    q = quote(engine)
    entered, release = threading.Event(), threading.Event()
    original = engine.public.market
    def slow_market(slug):
        entered.set()
        assert release.wait(5)
        return original(slug)
    engine.public.market = slow_market
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(engine.execute, q, 'Entry')
        assert entered.wait(2)
        try:
            paused = pool.submit(engine.pause, True)
            assert paused.result(timeout=1)['paused']
            assert engine.status()['paused']
        finally:
            release.set()
        with pytest.raises(TradingError, match='pausadas'):
            future.result(timeout=2)


def test_slow_tool_does_not_block_event_loop(engine):
    server = create_server(engine.settings, engine)
    original = engine.status
    def slow():
        time.sleep(0.3)
        return original()
    engine.status = slow
    async def check():
        started = time.monotonic()
        task = asyncio.create_task(server.call_tool('get_status', {}))
        await asyncio.sleep(0.04)
        assert time.monotonic() - started < 0.2
        await task
    asyncio.run(check())


def test_exposure_and_reduce_only(engine):
    engine = Engine(replace(engine.settings, market_exposure=Decimal('6')), engine.public)
    engine.execute(quote(engine), 'Entry')
    with pytest.raises(TradingError) as exc:
        engine.execute(quote(engine), 'Too much in one market')
    assert exc.value.code == 'MARKET_EXPOSURE_LIMIT'
    engine.reduce_only(True)
    with pytest.raises(TradingError) as exc:
        engine.execute(quote(engine), 'No buys')
    assert exc.value.code == 'REDUCE_ONLY'
    assert engine.execute(quote(engine, side='SELL', amount='10', limit_price='0.4'), 'Reduce')['status'] == 'simulated'
    assert engine.status()['open_or_pending_tokens'] == 0


def test_stop_automatic_attachment_restart_and_single_exit(engine):
    entry = engine.execute(quote(engine), 'Entry with stop', stop_loss_percent='20')
    assert entry['stop_loss_id']
    restarted = Engine(engine.settings, engine.public)
    stops = Stops(restarted)
    stops.tick()
    stops.tick()
    stops.tick()
    assert len(restarted.history()['orders']) == 2
    assert stops.list()['stops'][0]['status'] == 'completed'
    assert restarted.portfolio()['positions'] == []
    assert any(e['kind'] == 'stop_created' for e in restarted.movements()['events'])


def test_stop_opt_in_pause_reduce_only_and_cancel(engine):
    entry = engine.execute(quote(engine), 'No automatic stop')
    assert Stops(engine).list()['stops'] == []
    stop = Stops(engine).create(entry['id'], trigger_price='0.4')
    engine.pause(True)
    Stops(engine).tick()
    assert len(engine.history()['orders']) == 1
    engine.pause(False)
    engine.reduce_only(True)
    Stops(engine).cancel(stop['id'])
    Stops(engine).tick()
    assert len(engine.history()['orders']) == 1
    Stops(engine).create(entry['id'], loss_percent='20')
    Stops(engine).tick()
    assert len(engine.history()['orders']) == 2


def test_stop_price_floor_never_loosened_and_trigger_latches(engine):
    engine.execute(quote(engine), 'Entry', stop_loss_percent='20', stop_slippage='0.02')
    engine.public.bid = '0.30'
    Stops(engine).tick()
    stop = Stops(engine).list()['stops'][0]
    assert stop['status'] == 'triggered'
    assert stop['last_error']['code'] == 'INSUFFICIENT_LIQUIDITY'
    assert len(engine.history()['orders']) == 1
    engine.public.bid = '0.45'  # recovery still exits a latched stop
    Stops(engine).tick()
    assert len(engine.history()['orders']) == 2
    assert decimal(engine.history()['orders'][0]['limit_price']) == Decimal('0.38')


def test_stop_after_manual_sale_does_not_sell_new_position(engine):
    entry = engine.execute(quote(engine), 'Original')
    Stops(engine).create(entry['id'], loss_percent='20')
    engine.execute(quote(engine, side='SELL', amount='10', limit_price='0.4'), 'Manual exit')
    engine.execute(quote(engine), 'Different position')
    Stops(engine).tick()
    assert len(engine.history()['orders']) == 3
    assert Stops(engine).list()['stops'][0]['status'] == 'completed'


def test_stop_newer_lot_cannot_sell_more_than_authorized(engine):
    engine.execute(quote(engine), 'Older buy')
    entry = engine.execute(quote(engine), 'Protected newer buy', stop_loss_percent='20')
    for _ in range(4):
        Stops(engine).tick()
    assert len(engine.history()['orders']) == 3
    assert decimal(engine.portfolio()['positions'][0]['shares']) == 10
    assert Stops(engine).list()['stops'][0]['status'] == 'completed'


def test_stop_duplicate_attachment_rolls_back_buy(engine):
    engine.execute(quote(engine), 'Protected', stop_loss_percent='20')
    before = engine.portfolio()['cash_usd']
    with pytest.raises(TradingError) as exc:
        engine.execute(quote(engine), 'Duplicate stop', stop_loss_percent='20')
    assert exc.value.code == 'STOP_EXISTS'
    assert engine.portfolio()['cash_usd'] == before


def test_stop_live_unknown_exit_never_resubmitted(engine):
    live = live_engine(engine)
    entry = live.execute(quote(live), 'Live fixture', stop_loss_percent='20')
    live.broker.confirm = True
    live.sync_orders()
    live.broker.fail = True
    Stops(live).tick()
    assert live.broker.submits == 2
    restarted = Engine(live.settings, live.public, live.broker)
    for _ in range(3):
        Stops(restarted).tick()
    assert live.broker.submits == 2
    assert Stops(restarted).list()['stops'][0]['status'] == 'waiting'


def test_stop_dust_and_expiry_visible(engine):
    entry = engine.execute(quote(engine), 'Entry')
    engine.execute(quote(engine, side='SELL', amount='6', limit_price='0.4'), 'Reduce')
    Stops(engine).create(entry['id'], loss_percent='20')
    Stops(engine).tick()
    assert Stops(engine).list()['stops'][0]['status'] == 'dust'


def test_process_lock_exclusion_and_release(tmp_path):
    first, second = ProcessLock(tmp_path / 'monitor.lock'), ProcessLock(tmp_path / 'monitor.lock')
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_monitor_executes_without_tool_polling(engine):
    engine = Engine(replace(engine.settings, feed_enabled=False, monitor_interval=1), engine.public)
    engine.execute(quote(engine), 'Protected', stop_loss_percent='20')
    monitor = Monitor(engine)
    monitor.start()
    try:
        deadline = time.monotonic() + 4
        while len(engine.history()['orders']) == 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(engine.history()['orders']) == 2
    finally:
        monitor.close()


def test_feed_exact_decimals_history_gaps_and_calibration(engine):
    feed = ChainlinkFeed(engine.store, engine.settings.assets)
    now = time.time()
    msg = {'topic':'crypto_prices_twap_thirty', 'payload':{'symbol':'btc/usd', 'timestamp':now*1000,
           'window_s':30, 'full_accuracy_value':'65000500000000000000000'}}
    assert feed.ingest(msg)
    assert feed.ingest(msg)
    insights = Insights(engine)
    history = insights.observations('btc', since=now - 10)
    assert len(history['observations']) == 1
    assert history['observations'][0]['value'] == '65000.5'
    context = insights.context('btc-updown-5m-1789254000')
    assert context['references'][0]['fresh']
    assert context['references'][0]['change_since_open_percent'] is None
    forecast = insights.forecast('btc-updown-5m-1789254000', 'up', '0.8', 'Fixture')
    assert insights.metrics()['brier_score'] is None
    with engine.store.transaction() as db:
        db.execute('INSERT INTO resolutions VALUES (?,?,?)', ('condition','1',now))
    assert decimal(insights.metrics()['brier_score']) == Decimal('0.04')


def test_movements_read_only_filter_and_restart(engine):
    receipt = engine.execute(quote(engine), 'Entry')
    engine.public.resolution = lambda *a: pytest.fail('history must not call public API')
    reopened = Engine(engine.settings, engine.public)
    records = reopened.movements(kind='trade', slug=receipt['market']['slug'])
    assert len(records['events']) == 1
    assert reopened.movements(after=records['next_cursor'])['events'] == []


def test_404_with_complete_post_trade_ids_can_finalize(engine):
    live = live_engine(engine)
    live.broker.submit = lambda signed: {'success': True, 'orderID':'0xorder', 'tradeIDs':['known-fill']}
    live.execute(quote(live), 'Entry')
    live.broker.reconcile = lambda *a: (None, [{'id':'known-fill', 'size':'10', 'price':'0.5', 'status':'CONFIRMED'}])
    live.sync_orders()
    assert live.history()['orders'][0]['status'] == 'confirmed'


def test_stale_fill_cannot_erase_known_confirmation(engine):
    live = live_engine(engine)
    live.execute(quote(live), 'Entry')
    remote = {'id':'0xorder','asset_id':'1','side':'BUY','status':'MATCHED','size_matched':'10'}
    fills = [{'id':'a','size':'5','price':'0.5','status':'CONFIRMED'},
             {'id':'b','size':'5','price':'0.5','status':'MATCHED'}]
    live.broker.reconcile = lambda *a: (remote, fills)
    live.sync_orders()
    live.broker.reconcile = lambda *a: (remote, [fills[1]])
    live.sync_orders()
    assert live.history()['orders'][0]['execution']['shares'] == '5'


def test_manual_sale_during_stop_quote_revalidates_lot(engine, monkeypatch):
    engine.execute(quote(engine), 'Protected', stop_loss_percent='20')
    original = engine.execute
    done = False
    def racing(quote_id, reason, **kwargs):
        nonlocal done
        if kwargs.get('_stop_id') and not done:
            done = True
            original(quote(engine, side='SELL', amount='10', limit_price='0.4'), 'Manual close before SL reserve')
            original(quote(engine), 'Fresh unprotected buy')
        return original(quote_id, reason, **kwargs)
    monkeypatch.setattr(engine, 'execute', racing)
    Stops(engine).tick()
    assert len(engine.history()['orders']) == 3
    assert Stops(engine).list()['stops'][0]['last_error']['code'] == 'INVENTORY_CHANGED'
    assert decimal(engine.portfolio()['positions'][0]['shares']) == 10


def test_stop_cancelled_during_quote_cannot_submit(engine, monkeypatch):
    engine.execute(quote(engine), 'Protected', stop_loss_percent='20')
    stop_id = Stops(engine).list()['stops'][0]['id']
    original = engine.quote
    def cancel_during_quote(*a, **k):
        result = original(*a, **k)
        Stops(engine).cancel(stop_id)
        return result
    monkeypatch.setattr(engine, 'quote', cancel_during_quote)
    Stops(engine).tick()
    assert len(engine.history()['orders']) == 1
    assert Stops(engine).list()['stops'][0]['status'] == 'cancelled'


def test_stop_resume_persisted_quote_after_crash(engine, monkeypatch):
    engine.execute(quote(engine), 'Protected', stop_loss_percent='20')
    original = engine.execute
    def crash(*a, **k):
        raise RuntimeError('simulated crash before reserving order')
    monkeypatch.setattr(engine, 'execute', crash)
    Stops(engine).tick()
    linked_id = Stops(engine).list()['stops'][0]['quote_id']
    assert linked_id
    monkeypatch.setattr(engine, 'execute', original)
    restarted = Engine(engine.settings, engine.public)
    Stops(restarted).tick()
    assert restarted.history()['orders'][0]['quote_id'] == linked_id
    assert len(restarted.history()['orders']) == 2


def test_two_concurrent_live_sells_reserve_only_one(engine):
    live = live_engine(engine)
    queries = [quote(live, side='SELL', amount='5', limit_price='0.4') for _ in range(2)]
    def sell(q):
        try:
            return live.execute(q, 'Concurrent sell')['status']
        except TradingError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(sell, queries))
    assert sorted(results) == ['ORDER_PENDING', 'submitted']
    assert live.broker.submits == 1


def test_no_sqlite_read_lock_blocks_writes(engine):
    with engine.store.transaction(write=False) as db:
        db.execute('SELECT * FROM state').fetchall()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(engine.pause, True).result(timeout=1)['paused']


def test_backup_preserves_wal_activity_without_overwrite(engine, tmp_path):
    import sqlite3
    engine.execute(quote(engine), 'Backup fixture')
    target = backup(engine.store.path, tmp_path / 'backup.sqlite')
    copied = sqlite3.connect(target)
    try:
        assert copied.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 1
        assert copied.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        copied.close()
    with pytest.raises(FileExistsError):
        backup(engine.store.path, target)


def test_share_archive_and_docs_have_no_private_paths(tmp_path):
    import re
    import zipfile
    import tomllib
    files = package_files()
    names = [p.relative_to(ROOT).as_posix() for p in files]
    assert '.env.example' in names and 'README.md' in names
    assert not any(n == '.env' or n.startswith(('data/', '.codex/', '.gemini/', 'polymarket-btc-5m/', 'polymarket-doge-5m/')) for n in names)
    output, digest, count = build(output=tmp_path / 'share.zip')
    assert len(digest) == 64 and count == len(files)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            content = archive.read(name).decode('utf-8')
            assert str(ROOT) not in content and ROOT.as_posix() not in content
    json.loads((ROOT / 'examples/mcp.json').read_text(encoding='utf-8'))
    tomllib.loads((ROOT / 'examples/codex.toml').read_text(encoding='utf-8'))
    for path in [ROOT / 'README.md', *(ROOT / 'docs').glob('*.md')]:
        text = path.read_text(encoding='utf-8')
        for link in re.findall(r'\]\(([^)]+)\)', text):
            if '://' not in link and not link.startswith('#'):
                assert (path.parent / link.split('#')[0]).exists(), (path, link)


def test_error_diagnostics_never_store_remote_secret(engine):
    server = create_server(engine.settings, engine)
    def broken():
        raise RuntimeError('SECRET_FIXTURE_SHOULD_NEVER_LEAK')
    engine.status = broken
    async def check():
        result = await server.call_tool('get_status', {})
        assert result.isError
        assert result.structuredContent['code'] == 'INTERNAL_ERROR'
        assert 'SECRET_FIXTURE_SHOULD_NEVER_LEAK' not in result.model_dump_json()
    asyncio.run(check())
    with engine.store.transaction(write=False) as db:
        row = db.execute('SELECT code,detail FROM tool_calls').fetchone()
        assert row['code'] == 'INTERNAL_ERROR'
        assert 'SECRET_FIXTURE_SHOULD_NEVER_LEAK' not in row['detail']
