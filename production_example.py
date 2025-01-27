# -*- coding: utf-8 -*-
"""
Recommended installs: pip install pytrends fredapi yfinance
Uses a number of live public data sources to construct an example production case.

While stock price forecasting is shown here, time series forecasting alone is not a recommended basis for managing investments!

This is a highly opinionated approach.
evolve = True allows the timeseries to automatically adapt to changes.

There is a slight risk of it getting caught in suboptimal position however.
It should probably be coupled with some basic data sanity checks.
"""
import json
import datetime
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt  # required only for graphs
from autots import AutoTS, load_live_daily, create_regressor

fred_key = None  # https://fred.stlouisfed.org/docs/api/api_key.html
forecast_name = "example"
graph = True  # whether to plot graphs
# https://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html#dateoffset-objects
frequency = "D"  # "infer" for automatic alignment, but specific offsets are most reliable
forecast_length = 28  # number of periods to forecast ahead
drop_most_recent = 1  # whether to discard the n most recent records (as incomplete)
num_validations = 2  # number of cross validation runs. More is better but slower, usually
validation_method = "similarity"  # "similarity", "backwards", "seasonal 364"
n_jobs = "auto"  # "auto" or set to number of CPU cores
prediction_interval = 0.9  # sets the upper and lower forecast range by probability range. Bigger = wider
initial_training = "auto"  # set this to True on first run, or on reset, 'auto' looks for existing template, if found, sets to False.
evolve = True  # allow time series to progressively evolve on each run, if False, uses fixed template
archive_templates = True  # save a copy of the model template used with a timestamp
save_location = None  # "C:/Users/Colin/Downloads"  # directory to save templates to. Defaults to working dir
template_filename = f"autots_forecast_template_{forecast_name}.csv"
forecast_csv_name = None  # f"autots_forecast_{forecast_name}.csv"  # or None, point forecast only is written
model_list = "default"
transformer_list = "fast"  # 'superfast'
transformer_max_depth = 2

if save_location is not None:
    template_filename = os.path.join(save_location, template_filename)
    if forecast_csv_name is not None:
        forecast_csv_name = os.path.join(save_location, forecast_csv_name)

if initial_training == "auto":
    initial_training = not os.path.exists(template_filename)
    if initial_training:
        print("Existing template not found.")

# set max generations based on settings, increase for slower but greater chance of highest accuracy
if initial_training:
    gens = 30
    models_to_validate = 0.2
    ensemble = ["simple", "distance", "horizontal-max", "horizontal-min"]
elif evolve:
    gens = 15
    models_to_validate = 0.3
    # you can include "simple" and "distance" but they can nest, and may get huge as time goes on...
    ensemble = ["horizontal-max", "horizontal-min"]
else:
    gens = 0
    models_to_validate = 0.99
    ensemble = ["horizontal-max", "horizontal-min"]

# only save the very best model if not evolve
if evolve:
    n_export = 30
else:
    n_export = 1  # wouldn't be a bad idea to do > 1, allowing some future adaptability

"""
Begin dataset retrieval
"""

df = load_live_daily(
    long=False,
    fred_key=fred_key,
    tickers=["MSFT", "PG"],
    trends_list=["forecasting"],
    earthquake_min_magnitude=5,
    weather_years=2,
    london_air_days=90,
)

df = df[df.index.year > 1999]
start_time = datetime.datetime.now()
# remove any data from the future
df = df[df.index <= start_time]
# remove series with no recent data
min_cutoff_date = start_time - datetime.timedelta(days=180)
most_recent_date = df.notna()[::-1].idxmax()
drop_cols = most_recent_date[most_recent_date < min_cutoff_date].index.tolist()
df = df.drop(columns=drop_cols)

# example regressor with some things we can glean from data and datetime index
# note this only accepts `wide` style input dataframes
regr_train, regr_fcst = create_regressor(
    df,
    forecast_length=forecast_length,
    frequency=frequency,
    drop_most_recent=drop_most_recent,
    scale=True,
    summarize="auto",
    backfill="bfill",
    fill_na="spline",
    holiday_countries=["US", "UK"],  # requires holidays package
    datepart_method="recurring",
)

# remove the first forecast_length rows (because those are lost in regressor)
df = df.iloc[forecast_length:]
regr_train = regr_train.iloc[forecast_length:]

print("data setup completed, beginning modeling")
"""
Begin modeling
"""

metric_weighting = {
    "smape_weighting": 0,  # 0
    "mae_weighting": 3,  # 2
    "rmse_weighting": 0,  # 1
    "containment_weighting": 0,
    'made_weighting': 3,
    "runtime_weighting": 0,
    "spl_weighting": 1,  # 2
    "contour_weighting": 0,  # 1
}

model = AutoTS(
    forecast_length=forecast_length,
    frequency=frequency,
    prediction_interval=prediction_interval,
    ensemble=ensemble,
    model_list=model_list,
    transformer_list=transformer_list,
    transformer_max_depth=transformer_max_depth,
    max_generations=gens,
    metric_weighting=metric_weighting,
    initial_template='random',
    aggfunc="sum",
    models_to_validate=models_to_validate,
    model_interrupt=True,
    num_validations=num_validations,
    validation_method=validation_method,
    constraint=2,
    drop_most_recent=drop_most_recent,  # if newest data is incomplete, also remember to increase forecast_length
    # no_negatives=True,
    # subset=100,
    # prefill_na=0,
    # remove_leading_zeroes=True,
    n_jobs=n_jobs,
    verbose=1,
)

if not initial_training:
    if evolve:
        model.import_template(template_filename, method="addon")
    else:
        model.import_template(template_filename, method="only")

model = model.fit(df, future_regressor=regr_train,)

prediction = model.predict(future_regressor=regr_fcst)

# Print the details of the best model
print(model)

"""
Process results
"""

# point forecasts dataframe
forecasts_df = prediction.forecast  # .fillna(0).round(0)
if forecast_csv_name is not None:
    forecasts_df.to_csv(forecast_csv_name)

forecasts_upper_df = prediction.upper_forecast
forecasts_lower_df = prediction.lower_forecast

# accuracy of all tried model results
model_results = model.results()
validation_results = model.results("validation")

# save a template of best models
if initial_training or evolve:
    model.export_template(
        template_filename, models="best", n=n_export, max_per_model_class=5
    )
    if archive_templates:
        arc_file = f"{template_filename.split('.csv')[0]}_{start_time.strftime('%Y%m%d%H%M')}.csv"
        model.export_template(arc_file, models="best", n=1)

model_parameters = json.loads(model.best_model["ModelParameters"].iloc[0])

if graph:
    col = model.df_wide_numeric.columns[-1]  # change column here
    plot_df = pd.DataFrame(
        {
            col: model.df_wide_numeric[col],
            "up_forecast": forecasts_upper_df[col],
            "low_forecast": forecasts_lower_df[col],
            "forecast": forecasts_df[col],
        }
    )
    plot_df[plot_df == 0] = np.nan
    plot_df.interpolate(method="cubic", inplace=True)
    fig, ax = plt.subplots(dpi=300, figsize=(8, 6))
    plot_df[plot_df.index.year >= 2021].plot(ax=ax)
    plt.show()

    if model.best_model["Ensemble"].iloc[0] == 2:
        # plt.subplots_adjust(bottom=0.4)
        model.plot_horizontal_transformers()
        plt.show()

        series = model.horizontal_to_df()
        if series.shape[0] > 25:
            series = series.sample(25, replace=False)
        series[["log(Volatility)", "log(Mean)"]] = np.log(
            series[["Volatility", "Mean"]]
        )

        fig, ax = plt.subplots(figsize=(6, 4.5))
        cmap = plt.get_cmap("tab10")  # 'Pastel1, 'cividis', 'coolwarm', 'spectral'
        names = series["Model"].unique()
        colors = dict(zip(names, cmap(np.linspace(0, 1, len(names)))))
        grouped = series.groupby("Model")
        for key, group in grouped:
            group.plot(
                ax=ax,
                kind="scatter",
                x="log(Mean)",
                y="log(Volatility)",
                label=key,
                color=colors[key].reshape(1, -1),
            )
        plt.title("Horizontal Ensemble: models choosen by series")
        plt.show()
        # plt.savefig("horizontal.png", dpi=300)

        if str(model_parameters["model_name"]).lower() == "mosaic":
            mosaic_df = model.mosaic_to_df()
            print(mosaic_df[mosaic_df.columns[0:5]].head(5))
