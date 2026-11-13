import pytest
from Code.decision import weather_context as wx


def body():
    days=[f'2026-11-{d:02d}' for d in range(12,19)]
    return {'daily':{'time':days,'precipitation_sum':[0]*7,'temperature_2m_max':[30]*7,'precipitation_probability_max':[0]*7},
            'daily_units':{'precipitation_sum':'mm','temperature_2m_max':'°C','precipitation_probability_max':'%'},
            'hourly':{'time':[d+f'T{h:02d}:00' for d in days for h in range(24)],'relative_humidity_2m':[70]*168,'wind_speed_10m':[12]*168},
            'hourly_units':{'relative_humidity_2m':'%','wind_speed_10m':'km/h'}}


def install(monkeypatch,data):
    class Response:
        status_code=200
        def json(self):return data
    monkeypatch.setattr(wx.requests,'get',lambda *a,**k:Response())


def test_humidity_and_wind_are_forecast_context_not_realized_conditions(monkeypatch):
    install(monkeypatch,body())
    days=wx.fetch(20,75)
    assert days[0]['humidity_mean_pct']==70 and days[0]['wind_max_kmh']==12


def test_missing_hourly_observation_remains_unknown(monkeypatch):
    data=body();data['hourly']['relative_humidity_2m'][0]=None;install(monkeypatch,data)
    assert wx.fetch(20,75)[0]['humidity_mean_pct'] is None


def test_invalid_units_or_duplicate_hours_are_rejected(monkeypatch):
    data=body();data['hourly_units']['wind_speed_10m']='m/s';install(monkeypatch,data)
    with pytest.raises(wx.fc.ForecastError):wx.fetch(20,75)
    data=body();data['hourly']['time'][1]=data['hourly']['time'][0];install(monkeypatch,data)
    with pytest.raises(wx.fc.ForecastError):wx.fetch(20,75)
