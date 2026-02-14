from __future__ import annotations

import asyncio
import calendar
import decimal
from datetime import date, datetime, timedelta
import logging
from zoneinfo import ZoneInfo
from typing import Any

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity, SensorDeviceClass
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import UpdateFailed, DataUpdateCoordinator, CoordinatorEntity

from .const import (
    BASE_URL,
    DEFAULT_NAME,
    DEFAULT_BILLING_START_DAY,
    DEFAULT_SUBSCRIPTION,
    DEFAULT_SURCHARGE_CENTS,
    CONF_NAME,
    CONF_BILLING_START_DAY,
    CONF_SITE_ID,
    CONF_SITE_IDS,
    CONF_SUBSCRIPTION,
    CONF_SURCHARGE_CENTS,
    CONF_TOKEN,
    DOMAIN,
    ISO_DATE,
    MAX_BILLING_START_DAY,
    MIN_BILLING_START_DAY,
    REQUEST_TIMEOUT,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_TOKEN): cv.string,
        vol.Optional(CONF_SITE_ID): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(
            CONF_BILLING_START_DAY, default=DEFAULT_BILLING_START_DAY
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_BILLING_START_DAY, max=MAX_BILLING_START_DAY)),
        vol.Optional(CONF_SURCHARGE_CENTS, default=DEFAULT_SURCHARGE_CENTS): vol.Coerce(
            float
        ),
        vol.Optional(CONF_SUBSCRIPTION, default=DEFAULT_SUBSCRIPTION): vol.Coerce(
            float
        ),
    }
)


def build_sensors(api: AmberApi, coordinator: AmberCoordinator, base_name: str, site_id: str):
    device_name = f"{base_name} ({site_id})"
    sensors: list[SensorEntity] = [
        AmberBalanceSensor(api=api, coordinator=coordinator, name="Month Total", device_name=device_name),
    ]

    metric_defs = [
        ("import_kwh", "Import kWh", "mdi:transmission-tower-import", "kWh", "total_increasing", None),
        ("export_kwh", "Export kWh", "mdi:transmission-tower-export", "kWh", "total_increasing", None),
        ("net_kwh", "Net Grid Consumption", "mdi:transmission-tower", "kWh", "total", None),
        ("import_value", "Import $", "mdi:cash-minus", "AUD", "total", "monetary"),
        ("export_value", "Export $", "mdi:cash-plus", "AUD", "total", "monetary"),
        ("energy_total", "Before Fees $", "mdi:chart-line", "AUD", "total", "monetary"),
        ("surcharge", "Surcharge $ (Daily)", "mdi:cash", "AUD", "total", "monetary"),
        ("subscription", "Subscription $ (Daily)", "mdi:card-account-details", "AUD", "total", "monetary"),
        ("fees", "Fees $", "mdi:cash-multiple", "AUD", "total", "monetary"),
        ("position", "Month Total $", "mdi:scale-balance", "AUD", "total", "monetary"),
        ("average_daily_cost", "Avg Daily $", "mdi:calculator", "AUD", "measurement", None),
        ("projected_month_total", "Projected Month $", "mdi:chart-timeline-variant", "AUD", "measurement", None),
        ("days_elapsed", "Days Elapsed", "mdi:calendar-check", "days", "measurement", None),
        ("days_remaining", "Days Remaining", "mdi:calendar-clock", "days", "measurement", None),
    ]
    for metric, label, icon, unit, state_class, device_class in metric_defs:
        sensors.append(
            AmberMetricSensor(
                coordinator=coordinator,
                api=api,
                name=label,
                device_name=device_name,
                metric=metric,
                icon=icon,
                unit=unit,
                state_class=state_class,
                device_class=device_class,
            )
        )
    
    # Add statistics sensors
    stats_defs = [
        ("best_day", "Best Day $", "mdi:trophy", "AUD"),
        ("worst_day", "Worst Day $", "mdi:thumb-down", "AUD"),
        ("most_average_day", "Most Average Day $", "mdi:chart-bell-curve", "AUD"),
        ("days_in_credit", "Days in Credit", "mdi:heart", "days"),
        ("days_owing", "Days Owing", "mdi:heart-broken", "days"),
    ]
    for metric, label, icon, unit in stats_defs:
        sensors.append(
            AmberMetricSensor(
                coordinator=coordinator,
                api=api,
                name=label,
                device_name=device_name,
                metric=metric,
                icon=icon,
                unit=unit,
            )
        )
    
    # Add diagnostic sensors
    diagnostic_defs = [
        ("nmi", "NMI", "mdi:identifier"),
        ("network", "Network", "mdi:transmission-tower"),
        ("status", "Status", "mdi:check-circle"),
        ("active_from", "Active From", "mdi:calendar"),
        ("channels", "Channels", "mdi:format-list-bulleted"),
    ]
    for metric, label, icon in diagnostic_defs:
        sensors.append(
            AmberDiagnosticSensor(
                api=api,
                name=label,
                device_name=device_name,
                metric=metric,
                icon=icon,
            )
        )
    
    # Add Last Update timestamp sensor
    sensors.append(
        AmberLastUpdateSensor(
            coordinator=coordinator,
            api=api,
            name="Last Update",
            device_name=device_name,
        )
    )
    
    return sensors


async def async_setup_platform(hass: HomeAssistant, config, add_entities, discovery_info=None):
    token = config[CONF_TOKEN]
    name = config[CONF_NAME]
    billing_start_day = config.get(CONF_BILLING_START_DAY, DEFAULT_BILLING_START_DAY)
    surcharge_cents = config[CONF_SURCHARGE_CENTS]
    subscription = config[CONF_SUBSCRIPTION]

    session = async_get_clientsession(hass)
    site_ids = []
    if config.get(CONF_SITE_ID):
        site_ids = [config[CONF_SITE_ID]]
    else:
        site_ids = await AmberApi.discover_sites(session, token)
    sensors = []
    for sid in site_ids:
        api = AmberApi(session, token, sid)
        coordinator = AmberCoordinator(
            hass,
            api,
            surcharge_cents=surcharge_cents,
            subscription=subscription,
            billing_start_day=billing_start_day,
            name=f"{name} ({sid[:6]})",
        )
        sensors.extend(build_sensors(api, coordinator, name, sid))
    add_entities(sensors, update_before_add=True)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    data = entry.data
    options = entry.options
    session = async_get_clientsession(hass)
    
    # Get token from options if available, otherwise from data
    token = options.get(CONF_TOKEN, data.get(CONF_TOKEN))
    billing_start_day = options.get(
        CONF_BILLING_START_DAY,
        data.get(CONF_BILLING_START_DAY, DEFAULT_BILLING_START_DAY),
    )
    surcharge_cents = options.get(CONF_SURCHARGE_CENTS, data.get(CONF_SURCHARGE_CENTS, DEFAULT_SURCHARGE_CENTS))
    subscription = options.get(CONF_SUBSCRIPTION, data.get(CONF_SUBSCRIPTION, DEFAULT_SUBSCRIPTION))
    
    site_ids = data.get(CONF_SITE_IDS) or []
    if not site_ids and data.get(CONF_SITE_ID):
        site_ids = [data[CONF_SITE_ID]]
    
    # Fetch site info for all sites at once
    try:
        all_sites_info = await AmberApi.fetch_all_sites_info(session, token)
    except Exception as err:
        _LOGGER.warning("Failed to fetch sites info: %s", err)
        all_sites_info = {}
    
    # Initialize hass.data storage for this domain/entry keyed by site_id
    domain_data = hass.data.setdefault(DOMAIN, {})
    entry_storage = domain_data.setdefault(entry.entry_id, {})
    lock = entry_storage.get("_lock")
    if lock is None:
        lock = asyncio.Lock()
        entry_storage["_lock"] = lock

    sensors = []
    async with lock:
        entry_storage["sites"] = {}
        site_bucket: dict[str, dict] = entry_storage["sites"]

        for sid in site_ids:
            api = AmberApi(session, token, sid)
            site_info = all_sites_info.get(sid, {})

            coordinator = AmberCoordinator(
                hass,
                api,
                surcharge_cents=surcharge_cents,
                subscription=subscription,
                billing_start_day=billing_start_day,
                name=f"{data.get(CONF_NAME, DEFAULT_NAME)} ({sid})",
            )
            # Perform initial coordinator refresh
            await coordinator.async_config_entry_first_refresh()

            # Store site_info in api for diagnostic sensors
            api._site_info = site_info
            site_bucket[sid] = {
                "coordinator": coordinator,
                "api": api,
                "site_info": site_info,
            }
            sensors.extend(
                build_sensors(api, coordinator, data.get(CONF_NAME, DEFAULT_NAME), sid)
            )
    async_add_entities(sensors, update_before_add=False)


class AmberApi:
    def __init__(self, session: aiohttp.ClientSession, token: str, site_id: str):
        self._session = session
        self._token = token
        self._site_id = site_id

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }

    @staticmethod
    async def discover_sites(session: aiohttp.ClientSession, token: str) -> list[str]:
        headers = AmberApi._headers(token)
        url = BASE_URL + "/sites"
        async with async_timeout.timeout(REQUEST_TIMEOUT):
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"GET {url} -> {resp.status}: {text[:200]}")
                data = await resp.json()
        site_ids = []
        if isinstance(data, list):
            for s in data:
                sid = s.get("id") or s.get("siteId") or s.get("site_id")
                if sid:
                    site_ids.append(str(sid))
        return site_ids
    
    @staticmethod
    async def fetch_all_sites_info(session: aiohttp.ClientSession, token: str) -> dict[str, dict]:
        """Fetch all sites with full information."""
        headers = AmberApi._headers(token)
        url = BASE_URL + "/sites"
        async with async_timeout.timeout(REQUEST_TIMEOUT):
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"GET {url} -> {resp.status}: {text[:200]}")
                data = await resp.json()
        
        sites_info = {}
        if isinstance(data, list):
            for s in data:
                sid = s.get("id") or s.get("siteId") or s.get("site_id")
                if sid:
                    sites_info[str(sid)] = s
        return sites_info

    async def fetch_usage(self, start: date, end: date) -> list[dict]:
        records: list[dict] = []
        cur = start
        while cur <= end:
            chunk_end = min(cur + timedelta(days=6), end)
            params = f"startDate={cur.strftime(ISO_DATE)}&endDate={chunk_end.strftime(ISO_DATE)}"
            data = await self._get(f"/sites/{self._site_id}/usage?{params}")
            if isinstance(data, list):
                records.extend(data)
            cur = chunk_end + timedelta(days=1)
        return records

    async def fetch_site_info(self) -> dict:
        return await self._get(f"/sites/{self._site_id}")

    async def _get(self, path: str):
        headers = self._headers(self._token)
        url = BASE_URL + path
        try:
            async with async_timeout.timeout(REQUEST_TIMEOUT):
                async with self._session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(f"GET {url} -> {resp.status}: {text[:200]}")
                    try:
                        return await resp.json()
                    except Exception as err:  # noqa: BLE001
                        text = await resp.text()
                        raise RuntimeError(
                            f"GET {url} -> invalid JSON response: {text[:200]}"
                        ) from err
        except asyncio.TimeoutError as err:
            raise RuntimeError(f"GET {url} timed out") from err


class AmberCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, api: AmberApi, surcharge_cents: float, subscription: float, billing_start_day: int, name: str):
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_method=self._async_update_data,
            update_interval=timedelta(hours=1),
        )
        self._api = api
        self._surcharge_cents = surcharge_cents
        self._subscription = subscription
        self._billing_start_day = max(MIN_BILLING_START_DAY, min(MAX_BILLING_START_DAY, billing_start_day))
        self._daily_cache: dict[str, dict] = {}
        self._cached_cycle_start: date | None = None
        self._cycle_length_current: int = calendar.monthrange(datetime.now().year, datetime.now().month)[1]
        self._nem_tz = ZoneInfo("Australia/Sydney")
        self.last_update_time: datetime | None = None
        self._previous_payload: dict[str, Any] | None = None

    async def _async_update_data(self):
        today = datetime.now(self._nem_tz).date()
        start, next_start = self._cycle_bounds(today)
        end = min(today - timedelta(days=1), next_start - timedelta(days=1))
        self._cycle_length_current = (next_start - start).days

        # On the first day of the cycle there is no usage yet; keep previous payload
        if end < start:
            _LOGGER.debug(
                "AmberCoordinator(%s): no usage yet for cycle starting %s, reusing previous payload",
                self._api._site_id,
                start,
            )
            self.last_update_time = datetime.now(self._nem_tz)
            if self._previous_payload:
                return self._previous_payload
            empty_payload = {
                "range_start": start.isoformat(),
                "range_end": start.isoformat(),
                "daily": [],
                "totals": self._totals([], self._cycle_length_current),
            }
            self._previous_payload = empty_payload
            return empty_payload

        if self._cached_cycle_start != start:
            self._daily_cache = {}
            self._cached_cycle_start = start

        records: list[dict] = []
        if start <= end:
            fetch_start: date | None = start
            if self._daily_cache:
                last_cached = max(date.fromisoformat(k) for k in self._daily_cache)
                if end > last_cached:
                    fetch_start = max(start, last_cached)
                else:
                    fetch_start = None
            if fetch_start and fetch_start <= end:
                try:
                    records = await self._api.fetch_usage(fetch_start, end)
                except Exception as err:
                    raise UpdateFailed(
                        f"Amber usage fetch failed for {self._api._site_id}: {err}"
                    ) from err

        daily = self._merge_daily(records, start, end)
        self._purge_out_of_range_cache(start, end)
        totals = self._totals(daily, self._cycle_length_current)
        range_end = end
        if daily:
            try:
                range_end = datetime.strptime(daily[-1]["date"], ISO_DATE).date()
            except Exception:
                pass
        
        # Update the last update time
        self.last_update_time = datetime.now(self._nem_tz)
        payload = {
            "range_start": start.isoformat(),
            "range_end": range_end.isoformat(),
            "daily": daily,
            "totals": totals,
        }
        self._previous_payload = payload

        _LOGGER.debug(
            "AmberCoordinator(%s) updated range %s -> %s (%d days, %d new records)",
            self._api._site_id,
            start,
            range_end,
            len(daily),
            len(records),
        )

        return payload

    def _merge_daily(self, records: list[dict], start: date, end: date):
        if records:
            self._daily_cache.update(self._summaries(records))
        daily = []
        cur = start
        while cur <= end:
            dkey = cur.isoformat()
            if dkey in self._daily_cache:
                daily.append(self._daily_cache[dkey])
            else:
                # Fill missing days with zero-usage record
                days_in_month = calendar.monthrange(cur.year, cur.month)[1]
                surcharge = float(self._surcharge_cents) / 100.0
                subscription = float(self._subscription) / days_in_month
                daily.append({
                    "date": dkey,
                    "import_kwh": 0.0,
                    "export_kwh": 0.0,
                    "import_value": 0.0,
                    "export_value": 0.0,
                    "energy_total": 0.0,
                    "surcharge": surcharge,
                    "subscription": subscription,
                    "position": surcharge + subscription,
                })
            cur += timedelta(days=1)
        return daily

    def _purge_out_of_range_cache(self, start: date, end: date) -> None:
        drop_keys = []
        for dkey in self._daily_cache:
            ddate = date.fromisoformat(dkey)
            if ddate < start or ddate > end:
                drop_keys.append(dkey)
        for dkey in drop_keys:
            self._daily_cache.pop(dkey, None)

    def _cycle_bounds(self, today: date) -> tuple[date, date]:
        """Return (start, next_start) for the current billing cycle."""
        day = self._billing_start_day
        if today.day >= day:
            start = date(today.year, today.month, day)
        else:
            prev_month_end = today.replace(day=1) - timedelta(days=1)
            start = date(prev_month_end.year, prev_month_end.month, day)
        next_start = self._next_cycle_start(start)
        return start, next_start

    def _next_cycle_start(self, start: date) -> date:
        month = start.month + 1
        year = start.year
        if month == 13:
            month = 1
            year += 1
        # billing start day capped to 28 so always valid
        return date(year, month, self._billing_start_day)
    def _summaries(self, records: list[dict]):
        by_date: dict[str, list[dict]] = {}
        for rec in records:
            d = rec.get("date")
            if not d:
                continue
            by_date.setdefault(d, []).append(rec)

        daily: dict[str, dict] = {}
        for key, day_records in by_date.items():
            summary = self._summarize_day(key, day_records)
            if summary:
                daily[key] = summary
        return daily

    def _summarize_day(self, dkey: str, records: list[dict]):
        if not records:
            return None
        by_channel: dict[str, decimal.Decimal] = {}
        import_kwh = 0.0
        export_kwh = 0.0

        def _round_money(value: decimal.Decimal) -> decimal.Decimal:
            return value.quantize(decimal.Decimal("1.00"), rounding=decimal.ROUND_HALF_UP)

        for rec in records:
            cost = rec.get("cost")
            if cost is None:
                continue
            kwh = rec.get("kwh") or 0.0
            cost_d = decimal.Decimal(str(cost)) / decimal.Decimal("100")
            channel_type = rec.get("channelType") or "unknown"
            by_channel[channel_type] = by_channel.get(channel_type, decimal.Decimal("0")) + cost_d
            if channel_type == "feedIn":
                export_kwh += abs(kwh)
            else:
                import_kwh += kwh

        import_value = decimal.Decimal("0")
        export_value = decimal.Decimal("0")
        for channel_type, total in by_channel.items():
            total_rounded = _round_money(total)
            if channel_type == "feedIn":
                export_value += total_rounded
            else:
                import_value += total_rounded

        energy_total = import_value + export_value

        surcharge = decimal.Decimal(str(self._surcharge_cents)) / decimal.Decimal("100")
        cycle_days = max(1, self._cycle_length_current)
        subscription = decimal.Decimal(str(self._subscription)) / decimal.Decimal(cycle_days)
        position = energy_total + surcharge + subscription
        return {
            "date": dkey,
            "import_kwh": import_kwh,
            "export_kwh": export_kwh,
            "import_value": float(import_value),
            "export_value": float(export_value),
            "energy_total": float(energy_total),
            "surcharge": float(surcharge),
            "subscription": float(subscription),
            "position": float(position),
        }

    def _totals(self, daily: list[dict], cycle_length: int):
        cycle_length = max(1, cycle_length)
        agg = {
            "import_kwh": 0.0,
            "export_kwh": 0.0,
            "net_kwh": 0.0,
            "import_value": 0.0,
            "export_value": 0.0,
            "energy_total": 0.0,
            "surcharge": 0.0,
            "subscription": 0.0,
            "fees": 0.0,
            "position": 0.0,
            "average_daily_cost": 0.0,
            "projected_month_total": 0.0,
            "days_elapsed": 0,
            "days_remaining": 0,
        }
        for d in daily:
            for k in agg:
                if k == "fees":
                    # Calculate fees as sum of surcharge and subscription
                    agg["fees"] += d.get("surcharge", 0.0) + d.get("subscription", 0.0)
                elif k == "net_kwh":
                    # Net = Export - Import (positive means net exporter)
                    agg["net_kwh"] += d.get("export_kwh", 0.0) - d.get("import_kwh", 0.0)
                elif k in d:
                    agg[k] += d[k]
        
        # Calculate derived metrics
        days_elapsed = len(daily)
        agg["days_elapsed"] = int(days_elapsed)
        
        if days_elapsed > 0:
            # Average daily cost
            agg["average_daily_cost"] = agg["position"] / days_elapsed
            agg["days_remaining"] = max(int(cycle_length - days_elapsed), 0)
            agg["projected_month_total"] = agg["average_daily_cost"] * cycle_length
        else:
            agg["days_remaining"] = cycle_length
        
        # Calculate statistics
        if daily:
            # Find best day (most credit - lowest position)
            best = min(daily, key=lambda x: x["position"])
            agg["best_day"] = best["position"]
            agg["best_day_date"] = best["date"]
            
            # Find worst day (most cost - highest position)
            worst = max(daily, key=lambda x: x["position"])
            agg["worst_day"] = worst["position"]
            agg["worst_day_date"] = worst["date"]
            
            # Find most average day (closest to $0)
            most_avg = min(daily, key=lambda x: abs(x["position"]))
            agg["most_average_day"] = most_avg["position"]
            agg["most_average_day_date"] = most_avg["date"]
            
            # Count days in credit vs owing
            agg["days_in_credit"] = int(sum(1 for d in daily if d["position"] < 0))
            agg["days_owing"] = int(sum(1 for d in daily if d["position"] > 0))
        else:
            agg["best_day"] = 0.0
            agg["best_day_date"] = None
            agg["worst_day"] = 0.0
            agg["worst_day_date"] = None
            agg["most_average_day"] = 0.0
            agg["most_average_day_date"] = None
            agg["days_in_credit"] = 0
            agg["days_owing"] = 0
        
        # Ensure day-based metrics remain integers when exposed via sensors
        for key in ("days_elapsed", "days_remaining", "days_in_credit", "days_owing"):
            agg[key] = int(agg.get(key, 0))

        return agg


class AmberBalanceSensor(CoordinatorEntity[AmberCoordinator], SensorEntity):
    _attr_should_poll = False

    def __init__(
        self,
        api: AmberApi,
        coordinator: AmberCoordinator,
        name: str,
        device_name: str,
    ):
        super().__init__(coordinator)
        self._api = api
        self._attr_name = name
        self._attr_icon = "mdi:currency-usd"
        self._attr_native_unit_of_measurement = "AUD"
        self._state = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, api._site_id)},
            name=device_name,
            manufacturer="Amber",
            model="Amber Balance",
        )
        self._attr_extra_state_attributes = {ATTR_ATTRIBUTION: "Data from amber.com.au"}

    @property
    def unique_id(self):
        site_suffix = (self._api._site_id or "default").lower()
        return f"{DOMAIN}_{site_suffix}_v2_position"

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))
        if self.coordinator.last_update_success:
            self._handle_coordinator_update()

    async def async_update(self):
        await self.coordinator.async_request_refresh()

    def _handle_coordinator_update(self):
        if not self.coordinator.data:
            return
        try:
            data = self.coordinator.data
            totals = data.get("totals", {})
            self._state = round(totals.get("position", 0.0), 2)

            last_update = None
            if self.coordinator.last_update_time:
                try:
                    last_update = self.coordinator.last_update_time.isoformat()
                except AttributeError:
                    last_update = str(self.coordinator.last_update_time)

            daily_records = data.get("daily", [])
            recent_daily = daily_records[-7:] if len(daily_records) > 7 else daily_records

            self._attr_extra_state_attributes = {
                ATTR_ATTRIBUTION: "Data from amber.com.au",
                "range_start": data.get("range_start"),
                "range_end": data.get("range_end"),
                "last_update": last_update,
                "import_kwh": round(totals.get("import_kwh", 0.0), 2),
                "export_kwh": round(totals.get("export_kwh", 0.0), 2),
                "net_kwh": round(totals.get("net_kwh", 0.0), 2),
                "import_value": round(totals.get("import_value", 0.0), 2),
                "export_value": round(totals.get("export_value", 0.0), 2),
                "energy_total": round(totals.get("energy_total", 0.0), 2),
                "surcharge": round(totals.get("surcharge", 0.0), 2),
                "subscription": round(totals.get("subscription", 0.0), 2),
                "fees": round(totals.get("fees", 0.0), 2),
                "position": round(totals.get("position", 0.0), 2),
                "average_daily_cost": round(totals.get("average_daily_cost", 0.0), 2),
                "projected_month_total": round(totals.get("projected_month_total", 0.0), 2),
                "days_elapsed": totals.get("days_elapsed", 0),
                "days_remaining": totals.get("days_remaining", 0),
                "best_day": round(totals.get("best_day", 0.0), 2),
                "best_day_date": totals.get("best_day_date"),
                "worst_day": round(totals.get("worst_day", 0.0), 2),
                "worst_day_date": totals.get("worst_day_date"),
                "most_average_day": round(totals.get("most_average_day", 0.0), 2),
                "most_average_day_date": totals.get("most_average_day_date"),
                "days_in_credit": totals.get("days_in_credit", 0),
                "days_owing": totals.get("days_owing", 0),
                "recent_daily": recent_daily,
            }
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error updating AmberBalanceSensor state: %s", err, exc_info=True)


class AmberMetricSensor(CoordinatorEntity[AmberCoordinator], SensorEntity):
    _attr_should_poll = False
    _DAY_METRICS = {"days_elapsed", "days_remaining", "days_in_credit", "days_owing"}

    def __init__(self, coordinator: AmberCoordinator, api: AmberApi, name: str, device_name: str, metric: str, icon: str, unit: str | None, state_class: str | None = None, device_class: str | None = None):
        super().__init__(coordinator)
        self._api = api
        self._metric = metric
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_device_class = device_class
        self._state = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, api._site_id)},
            name=device_name,
            manufacturer="Amber",
            model="Amber Balance",
        )

    @property
    def unique_id(self):
        site_suffix = (self._api._site_id or "default").lower()
        return f"{DOMAIN}_{site_suffix}_v2_{self._metric}"

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))
        if self.coordinator.last_update_success:
            self._handle_coordinator_update()

    async def async_update(self):
        await self.coordinator.async_request_refresh()

    def _handle_coordinator_update(self):
        if not self.coordinator.data:
            return
        totals = self.coordinator.data.get("totals", {})
        val = totals.get(self._metric)
        if val is not None:
            if isinstance(val, decimal.Decimal):
                val = float(val)
            if isinstance(val, (int, float)):
                if self._metric in self._DAY_METRICS:
                    self._state = int(round(float(val)))
                else:
                    self._state = round(float(val), 2)
            else:
                self._state = val

            if self._metric == "position" and isinstance(val, (int, float)):
                if val < 0:
                    self._attr_icon = "mdi:heart"
                elif val > 0:
                    self._attr_icon = "mdi:heart-broken"
                else:
                    self._attr_icon = "mdi:scale-balance"

        if self._metric in ["best_day", "worst_day", "most_average_day"]:
            date_key = f"{self._metric}_date"
            date_val = totals.get(date_key)
            if date_val:
                self._attr_extra_state_attributes = {
                    "date": date_val,
                    ATTR_ATTRIBUTION: "Data from amber.com.au",
                }

        self.async_write_ha_state()


class AmberDiagnosticSensor(SensorEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, api: AmberApi, name: str, device_name: str, metric: str, icon: str):
        self._api = api
        self._metric = metric
        self._attr_name = name
        self._attr_icon = icon
        self._state = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, api._site_id)},
            name=device_name,
            manufacturer="Amber",
            model="Amber Balance",
        )

    @property
    def unique_id(self):
        site_suffix = (self._api._site_id or "default").lower()
        return f"{DOMAIN}_{site_suffix}_v2_diag_{self._metric}"

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self):
        self._update_from_site_info()

    async def async_update(self):
        self._update_from_site_info()

    def _update_from_site_info(self):
        site_info = getattr(self._api, "_site_info", None)
        if not site_info:
            _LOGGER.debug("No site info available for diagnostic sensor %s", self._metric)
            return
        
        _LOGGER.debug("Updating diagnostic sensor %s with site_info: %s", self._metric, site_info)
        
        if self._metric == "nmi":
            self._state = site_info.get("nmi")
        elif self._metric == "network":
            self._state = site_info.get("network")
        elif self._metric == "status":
            self._state = site_info.get("status")
        elif self._metric == "active_from":
            self._state = site_info.get("activeFrom")
        elif self._metric == "channels":
            channels = site_info.get("channels", [])
            if channels:
                channel_info = []
                for ch in channels:
                    ch_type = ch.get("type", "unknown")
                    tariff = ch.get("tariff", "")
                    identifier = ch.get("identifier", "")
                    channel_info.append(f"{identifier}: {ch_type} ({tariff})")
                self._state = ", ".join(channel_info)
        
        _LOGGER.debug("Diagnostic sensor %s state set to: %s", self._metric, self._state)
        self.async_write_ha_state()


class AmberLastUpdateSensor(CoordinatorEntity[AmberCoordinator], SensorEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: AmberCoordinator, api: AmberApi, name: str, device_name: str):
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_icon = "mdi:clock-outline"
        self._api = api
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, api._site_id)},
            name=device_name,
            manufacturer="Amber",
            model="Amber Balance",
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))
        if self.coordinator.last_update_success:
            self._handle_coordinator_update()

    @property
    def unique_id(self):
        site_suffix = (self._api._site_id or "default").lower()
        return f"{DOMAIN}_{site_suffix}_v2_last_update"

    @property
    def native_value(self):
        if self.coordinator.last_update_time:
            return self.coordinator.last_update_time
        return None
    
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug(
            "AmberLastUpdateSensor updating, coordinator.last_update_time: %s",
            self.coordinator.last_update_time,
        )
        self._attr_extra_state_attributes = {
            "last_update_success": self.coordinator.last_update_success,
        }
        self.async_write_ha_state()
