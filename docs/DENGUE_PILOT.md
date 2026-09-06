# Rio de Janeiro dengue pilot

This is an experimental forecast of **weekly reported dengue cases in Rio de Janeiro, Brazil (IBGE 3304557)**. It does not predict clinical severity, deaths, healthcare demand, or a validated probability of an epidemic. It is not validated or endorsed by WHO.

The pilot makes a specific, measurable comparison: does a small autoregressive model improve on reporting the last observed count or the count 52 weeks earlier? A second candidate adds historical temperature and humidity. Google Trends, social media and aviation data are not used by this model.

## Source and target

The public [InfoDengue API and dictionary](https://info.dengue.mat.br/services/api) provide weekly municipal aggregates. The query requests dengue for Rio, epidemiological weeks 1–53, from 2015 through the current UTC year. `data_iniSE` identifies a Sunday; numeric JSON dates are milliseconds since the Unix epoch. Only municipal totals (`Localidade_id=0`) are accepted. Rows must be unique, finite, nonnegative integer case counts, sorted on a weekly grid. Missing weeks are **not zero-filled**. A gap pauses forecasts.

The target is `casos`: reported cases, including suspected cases. It is **not** a count of laboratory-confirmed infections. InfoDengue explains the surveillance and clinical/epidemiological classification in its [methods overview](https://info.dengue.mat.br/informacoes/). Population denominators, hospitalizations and deaths are not forecast by this pilot.

`casos_est` is InfoDengue's separate nowcast. It appears only as contextual information for reporting delay and is never a training label or feature. Neither `Rt`, `nivel`, `p_rt1` nor downstream alert variables enter the model. For example, the source snapshot retrieved on 6 September 2026 reported 95 cases for the week beginning 23 August, while the source nowcast was 227. Those numbers describe different quantities and must not be interchanged.

Reported cases are revised retrospectively. The weather series can also reflect updated reanalysis data. **The historical evaluation uses the latest downloaded series, not the data available to a forecaster at each historical issue date.** It therefore cannot establish real-time accuracy and may be optimistic. Excluding the latest four outcome weeks from scoring reduces recent truncation but does not solve this issue.

Weather fields are the weekly average of daily minimum temperatures (`tempmin`, degrees Celsius) and the weekly average of daily maximum relative humidities (`umidmax`, percent), as defined by InfoDengue. Null or invalid weather remains null. The weather candidate skips training or prediction origins without its required four consecutive weeks of weather; the other candidates retain valid case information. Missing meteorology never means zero temperature or humidity. No future weather observation or forecast is inserted into historical features.

## Forecast dates and data delay

All issue dates use UTC. The current epidemiological week starts on the most recent Sunday. Forecast targets are the **four following Sundays**, so every target week begins strictly after the issue date, even for a Friday run. A forecast is for the entire target week, not an instantaneous daily count.

The observed data may lag behind that calendar origin. The model uses a separate direct horizon equal to the future target minus the last complete observed week. For an issue on 6 September 2026, with observations through the week of 23 August, the targets start on 13 September, 20 September, 27 September and 4 October. These are calendar horizons 1–4 and data horizons 3–6. Historical fitting and evaluation use the same delay-adjusted distances. The payload includes both horizon definitions, `origin_week` and `data_origin_week`.

An incomplete current-week source row is retained in the displayed history but excluded from training. Forecasts pause when the source is more than two completed weeks behind the latest complete calendar week, when the source refresh fails, when continuous history is insufficient, or when model evaluation lacks the necessary coverage. Recent reported counts can still be substantially incomplete even when these freshness checks pass. Forecasts do not imply that the latest source counts are final.

## Candidate models

Four candidates are compared using exactly the same eligible evaluation origins:

1. **Persistence:** repeat the latest observed reported count at every horizon.
2. **Seasonal:** use the count exactly 52 weeks before the target. This is a simple benchmark, not a perfect epidemiological-calendar alignment across 53-week years.
3. **Cases + seasonality:** ridge regression for `log(1 + reported cases)`, with case lags 0, 1, 2, 3, 4 and 52 weeks, an intercept, and annual sine/cosine terms.
4. **Cases + seasonality + weather:** the same case/calendar inputs plus current and trailing-four-week means of minimum temperature and maximum humidity.

Each horizon has a separate fitted regression. Features are generated only from the available-data cutoff and earlier weeks. A training pair is added only once its target week is observed at or before the current cutoff. The models update on an expanding window; later test origins may learn earlier test outcomes once observed, but test outcomes never select the model or calibrate its uncertainty bands.

The implementation uses the Python standard library, sufficient statistics and a small pivoted linear-system solver. The L2 penalty is fixed at 1, excluding the intercept. Temperatures are scaled by 40 and humidity by 100 before fitting. At least 156 valid training pairs are required; the 52-week case lag consumes a further year of initial history. Predictions use the inverse log transform, clipped to nonnegative counts. A numerical ceiling of ten million applies to predictions and interval endpoints. No hyperparameter search is performed. These choices are simple development baselines, not an exhaustive test of possible weather models.

## Chronological evaluation and selection

The boundaries and selection rule are defined in code rather than optimized using the final test results:

| Role | Dates | Use |
| --- | --- | --- |
| Initial training | 2015–2018 | Initial history for expanding fits |
| Development | 2019–2021 target weeks | Select the baseline and candidate |
| Interval calibration | 2022–2023 | Estimate horizon-specific error widths |
| Test | 2024 through four weeks before the latest observation | Report errors and interval coverage |

Calibration origins must have an **available-data cutoff on or after 1 January 2022**, and their targets must end by 31 December 2023. Test origins must have a cutoff on or after 1 January 2024. This boundary embargo prevents a January target with a December issue cutoff from using model selection or calibration outcomes that were still in the future. Target dates remain within each partition.

The better of persistence and seasonal prediction is selected on development mean absolute error (MAE). The better ridge candidate is promoted only if its development MAE is more than 5% lower than that selected baseline. Otherwise the baseline is retained. MAE is computed across all horizon/origin pairs for which every candidate can predict, so comparisons use matched samples. Metrics include the number of scored pairs; pairs overlap and are not independent observations. A candidate with a better final test result does **not** replace the development-selected model.

The payload publishes development and test MAE for all four candidates, plus per-horizon baseline/cases/weather MAE, sample sizes and empirical interval coverage. Test performance is a revised-data hindcast, **not independent prospective validation**. As the source revises historical records or the operational delay changes, the computed evaluation may also change. The version and data fingerprints identify the exact issue being reported.

At the 6 September 2026 development check, the selected cases model had development MAE 34.80, compared with 66.59 for persistence. On the embargoed revised-data test it had MAE 803.94 versus 851.74 for persistence, about 5.6% lower. The weather candidate had test MAE 797.81 but was not selected because development had favored the cases model. This modest advantage on one city and one revised snapshot does not establish clinical utility or show that weather is generally unnecessary. These values are an example snapshot; the dashboard shows its current run.

## Experimental uncertainty bands

For each candidate and horizon, calibration errors are absolute differences in `log(1 + cases)` over eligible 2022–2023 origins. The width is the sorted residual at rank `ceil((n + 1) × 0.8)`, bounded by the available sample size. A symmetric interval in log space is transformed back to nonnegative counts. The result is labelled an **empirical 80% band**.

The time series is autocorrelated and can change epidemic regime. There is no guarantee of 80% future coverage, and the bands do not capture all notification revisions. Actual held-out coverage is shown per horizon. The bands are not a calibrated probability of serious disease or an epidemic. If current inputs required by the selected candidate are missing, the preselected baseline and its own calibration bands are used with an explicit note.

## Collection, cache and publication

Run `python3 dengue_forecast.py` to write `dengue_forecast.json` and the private runner cache `dengue_history_cache.json`. Successful source responses are cached for 24 hours. A refresh uses one HTTPS request, a 25-second timeout, a four-megabyte response limit and a fixed city endpoint. Failed refreshes may be retried by the next scheduled scan; a stale cached history remains visible but **no fresh forecast is issued**. Errors are represented by a generic exception class, not response bodies or secrets. An unavailable pilot does not prevent the broader signal dashboard from publishing.

The published JSON contains only municipal aggregate history, forecast/evaluation output, source metadata and limitations. It includes model version, issue time, raw-response SHA-256 and canonical normalized-data SHA-256. The source data remains attributed to InfoDengue; the repository's software license does not grant new rights over third-party data.

`validate_payload` rejects inconsistent dates, past forecast weeks, missing fingerprints, stale data presented as ready, invalid counts/intervals, and incomplete evaluation metadata before publication. Writes are atomic. The source cache is not intended as a public file.

## Prospective evaluation required next

Preserve the first successfully issued forecast each UTC week with its complete normalized input history, model version, data fingerprint and issue timestamp. Do not overwrite earlier forecasts when source notifications are revised. This is the role of the separate publication archive; its existence is not evidence that prospective performance has already been measured.

Future scoring should register the target and outcome-maturation rule before observing results, retain all data revisions, score frozen forecasts against outcomes after a stated reporting delay, and report MAE, interval coverage, bias and performance during rising incidence. Record source outages and unavailable forecasts rather than silently removing them from evaluation. An epidemic-threshold or severe-disease model would require a separate local event definition, suitable outcome data, calibration and external validation.

`python3 -m unittest test_dengue_forecast` exercises missing/invalid data, cache failure, future-feature and future-target isolation, independence of model selection and interval calibration from test outcomes, chronological boundary embargoes, future forecast dates and publication guards. Synthetic tests validate implementation behavior; they do not validate epidemiological performance.
