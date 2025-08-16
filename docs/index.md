---
layout: default
title: ESY Sunhome Battery Home Assistant Integration
---

# ESY Sunhome Battery Home Assistant Integration

Here i'll be documenting my journey to optimize and automate my ESY sunhome battery. Prior to having the battery installed, i had a 10kW PV system so I had a bunch of existing automations to control devices.

![ESY Sunhome Integration](/docs/screenshot.png)

## Dashboard

![ESY Sunhome Integration](/docs/screenshot.png)

I've included the yaml at the bottom of the page if you'd like to include a chart for your dashboard, firstly though i'll go over the sensors and you should also configure the energy dashboard based on the sensors created.

## Utility Meters

It's worth noting that i have half hour net metering so so i have a bunch of half hour sensors.

{% raw %}
```yaml

hourly_cost:
  source: input_number.lifetime_energy_charge
  cycle: hourly
  net_consumption: true
  unique_id: hourly_cost

daily_cost:
  source: input_number.lifetime_energy_charge
  cycle: daily
  net_consumption: true
  unique_id: daily_cost

monthly_cost:
  source: input_number.lifetime_energy_charge
  cycle: monthly
  net_consumption: true
  unique_id: monthly_cost

production_half_hourly:
  source: sensor.energy_from_solar
  cron: "*/30 * * * *"
  unique_id: production_half_hourly
  
production_today:
  source: sensor.energy_from_solar
  cycle: daily
  unique_id: production_today
  
production_this_month:
  source: sensor.energy_from_solar
  cycle: monthly
  unique_id: production_this_month
  
consumption_half_hourly:
  source: sensor.energy_to_home
  cron: "*/30 * * * *"
  unique_id: consumption_half_hourly
  
export_half_hourly:
  source: sensor.energy_to_grid
  cron: "*/30 * * * *"
  unique_id: export_half_hourly
  
import_half_hourly:
  source: sensor.energy_from_grid
  cron: "*/30 * * * *"
  unique_id: import_half_hourly
  
energy_to_battery_half_hourly:
  source: sensor.energy_to_battery
  cron: "*/30 * * * *"
  unique_id: energy_to_battery_half_hourly
  
energy_from_battery_half_hourly:
  source: sensor.energy_from_battery
  cron: "*/30 * * * *"
  unique_id: energy_from_battery_half_hourly
  
consumption_today:
  source: sensor.energy_to_home
  cycle: daily
  unique_id: consumption_today
  
consumption_this_month:
  source: sensor.energy_to_home
  cycle: monthly
  unique_id: consumption_this_month

{% endraw %}
```markdown

## Sensors

{% raw %}
```yaml

- platform: integration
  source: sensor.esy_sunhome_battery_import
  name: Energy To Battery
  unique_id: energy_to_battery
  unit_prefix: k
  round: 2
  method: left
  max_sub_interval:
    minutes: 1

- platform: integration
  name: Energy From Solar
  unique_id: energy_from_solar
  source: sensor.esy_sunhome_pv_power
  unit_prefix: k
  round: 2
  method: left
  max_sub_interval:
    minutes: 1

- platform: integration
  name: Energy From Battery
  unique_id: energy_from_battery
  source: sensor.esy_sunhome_battery_export
  unit_prefix: k
  round: 2
  method: left
  max_sub_interval:
    minutes: 1

- platform: integration
  name: Energy From Grid
  unique_id: energy_from_grid
  source: sensor.esy_sunhome_grid_import
  unit_prefix: k
  round: 2
  method: left
  max_sub_interval:
    minutes: 1

- platform: integration
  name: Energy To Grid
  unique_id: energy_to_grid
  source: sensor.esy_sunhome_grid_export
  unit_prefix: k
  round: 2
  method: left
  max_sub_interval:
    minutes: 1

- platform: integration
  name: Energy To Home
  unique_id: energy_to_home
  source: sensor.esy_sunhome_load_power
  unit_prefix: k
  round: 2
  method: left
  max_sub_interval:
    minutes: 1


{% endraw %}
```markdown

## Template & Stats sensors

I created these using the UI, i haven't tested the yaml so please test that they work or just create them using the UI.

{% raw %}
```yaml

# -------------------------
# TEMPLATE ENTITIES
# -------------------------
template:
  - sensor:
        # Current Rate is the rate descriptor
      - name: "Current Rate"
        unique_id: 01JSJ961WXK9QCB3RM7KFJ8CA4
        icon: mdi:meter-electric-outline
        state: >
            {% if states('sensor.home_general_price_descriptor') not in ['unavailable', 'unknown', 'none'] %}
              {{ states('sensor.home_general_price_descriptor').replace('_', ' ') | title }}
            {% else %}
              {{ this.state }}
            {% endif %}
      - name: "Current Charge"
        unique_id: 01JSJ9HDRYPPTWZKJ39FJN1JJH
        icon: mdi:meter-electric
        unit_of_measurement: "$"
        state: >
            {% if states('sensor.home_general_price') not in ['unavailable', 'unknown', 'none'] %}
              {{ states('sensor.home_general_price') }} 
            {% else %}
              {{ this.state }}
            {% endif %}
      - name: "Current Export Rate"
        # Current Export Rate is the Descriptor
        unique_id: 01K2K91A63BK2XJP3PPV03K66W
        state: >
            {% if states('sensor.home_feed_in_price_descriptor') not in ['unavailable', 'unknown', 'none'] %}
              {{ states('sensor.home_feed_in_price_descriptor').replace('_', ' ') | title }}
            {% else %}
              {{ this.state }}
            {% endif %}

  - number:
      # Half Hourly Accumulating Charge
      - name: "Half Hourly Accumulating Charge"
        unique_id: 01JWVVB9QHP5QGNVTWP67VEB72
        unit_of_measurement: "$"
        min: 0
        max: 100
        step: 1
        state: >
            {% set consumption = states('sensor.half_hour_max_import') | float(0) %}
            {% set production = states('sensor.half_hour_max_export') | float(0) %}
            {% set energy = consumption - production | float(0) %}
            {% set rate = states('sensor.current_charge') | float(0) %}
            {% set export_rate = states('number.current_export_charge') | float(0) %}
            {% if energy > 0 %}
              {{ (states('input_number.lifetime_energy_charge') | float(0)) + (energy * rate) }}
            {% else %}
              {{ (states('input_number.lifetime_energy_charge') | float(0)) + (energy * export_rate) }}
            {% endif %}

  - number:
      # Current Export Charge
      - name: "Current Export Charge"
        unique_id: 01K2K8FGHKB8H12RPE7NJB3CGT
        unit_of_measurement: "$"
        min: 0
        max: 100
        step: 1
        state: >
            {% if states('sensor.home_feed_in_price') not in ['unavailable', 'unknown', 'none'] %}
              {{ states('sensor.home_feed_in_price') }} 
            {% else %}
              {{ this.state }}
            {% endif %}

# -------------------------
# STATISTICS SENSORS
# -------------------------
sensor:
  # Half Hour Max Consumption (max over last 30 minutes)
  - platform: statistics
    name: "Half Hour Max Consumption"
    unique_id: 01JWVSZQDGE6RWNK7YYJ7TN7DE
    entity_id: sensor.consumption_half_hourly
    state_characteristic: value_max
    max_age:
      minutes: 30

  # Half Hour Max Production
  - platform: statistics
    name: "Half Hour Max Production"
    unique_id: 01JWVT1R5H5JP7SNDQ928A5X2S
    entity_id: sensor.production_half_hourly
    state_characteristic: value_max
    max_age:
      minutes: 30

  # Half Hour Max Export
  - platform: statistics
    name: "Half Hour Max Export"
    unique_id: 01K2PKKVJY1TXTPWVAEAEKNGVA
    entity_id: sensor.export_half_hourly
    state_characteristic: value_max
    max_age:
      minutes: 30

  # Half Hour Max Import
  - platform: statistics
    name: "Half Hour Max Import"
    unique_id: 01K2PKP0GPBDG2C8M9FEDPSZN1
    entity_id: sensor.import_half_hourly
    state_characteristic: value_max
    max_age:
      minutes: 30

# -------------------------
# FILTERED (ROLLING) SENSORS
# -------------------------
sensor:
  # Home Battery Export Rolling Average (time-based SMA example)
  - platform: filter
    name: "Home Battery Export Rolling Average"
    unique_id: 01K2CKT99F88XACNM0HKB9DKMD
    entity_id: sensor.esy_sunhome_battery_export
    filters:
      - filter: time_simple_moving_average
        window_size: "00:30"
        precision: 0

  # Solar Production EMA (low-pass = exponential smoothing)
  - platform: filter
    name: "Solar Production EMA"
    unique_id: 01K2D9V7ZMYNPT51N4TE9AA0M5
    entity_id: sensor.esy_sunhome_pv_power
    filters:
      - filter: lowpass
        time_constant: 10
        precision: 0

{% endraw %}
```markdown


## Automations

These are some helper automations i tweak before i set the battery to import or export. I have set up the ESY "Battery Energy Management" mode to elecricity purchase from 00:00 to 23:59 so when i switch to this operating mode, i know it will charge the battery.. yours will be different if you haven't configured the mode.. This isn't yet available through the HACS integration but will be available soon.

{% raw %}
```yaml

alias: Stop Electricty Selling
description: >-
  When battery charge drops below 51% or the feed-in price drops below 20c and
  the battery is in sell mode, then switch back to regular mode
triggers:
  - trigger: numeric_state
    entity_id:
      - sensor.esy_sunhome_battery_state_of_charge
    below: 51
  - trigger: numeric_state
    entity_id:
      - sensor.home_feed_in_price
    for:
      hours: 0
      minutes: 0
      seconds: 10
    below: 0.2
conditions:
  - condition: state
    entity_id: select.esy_sunhome_operating_mode
    state: Electricity Sell Mode
actions:
  - action: select.select_option
    target:
      entity_id: select.esy_sunhome_operating_mode
    data:
      option: Regular Mode
  - action: notify.mobile_app_sm_s938b
    metadata: {}
    data:
      message: Switched to regular mode
      title: Battery mode update
mode: single

#############################################################################

alias: Stop Charging
description: >-
  When battery charge drops is above 75% or the general price is above 9c and
  the battery is in buy mode, then switch back to regular mode
triggers:
  - trigger: numeric_state
    entity_id:
      - sensor.esy_sunhome_battery_state_of_charge
    above: 75
  - trigger: numeric_state
    entity_id:
      - sensor.home_general_price
    for:
      hours: 0
      minutes: 0
      seconds: 10
    above: 0.09
conditions:
  - condition: state
    entity_id: select.esy_sunhome_operating_mode
    state: Battery Energy Management
actions:
  - action: select.select_option
    target:
      entity_id: select.esy_sunhome_operating_mode
    data:
      option: Regular Mode
  - action: notify.mobile_app_sm_s938b
    metadata: {}
    data:
      message: Stopped Charging
mode: single

#############################################################################

alias: Energy Cost Half Hourly
description: >-
  Calculates the net charge for each half hour and adds it to lifetime energy
  charge.
triggers:
  - trigger: time_pattern
    minutes: /30
conditions: []
actions:
  - action: input_number.set_value
    target:
      entity_id: input_number.lifetime_energy_charge
    metadata: {}
    data:
      value: "{{ states('number.half_hourly_accumulating_charge') | float(0) }}"
mode: single

#############################################################################

alias: Energy Daily Access Charges
description: >-
    Adds the daily access charge and amber fee to the lifetime energy charge sensor"
triggers:
  - trigger: time_pattern
    hours: "0"
    minutes: "0"
    seconds: "1"
conditions: []
actions:
  - action: input_number.set_value
    target:
      entity_id: input_number.lifetime_energy_charge
    metadata: {}
    data:
      value: "{{ states('input_number.lifetime_energy_charge') | float(0) + 0.9790 }}"
  - action: input_number.set_value
    metadata: {}
    data:
      value: >
        {% set dt = now() %} 

        {% set days_this_month = (dt.replace(month=dt.month % 12 + 1, day=1) -
        timedelta(days=1)).day %} 

        {% set charge = (12.5/days_this_month) | float(0) %}

        {{ states('input_number.lifetime_energy_charge') | float(0) + charge }}
    target:
      entity_id: input_number.lifetime_energy_charge
mode: single


{% endraw %}
```markdown


## Dashboard

In case you're interested in the components that make up my dashboard, i have a few HACS cards -> apexcharts card, card-mod.. here is the yaml:

{% raw %}
```yaml
  - type: sections
    title: Energy Bill
    path: energy-bill
    icon: mdi:lightning-bolt-circle
    sections:
      - type: grid
        cards:
          - type: heading
            heading_style: title
            heading: Forecast Energy Production
            grid_options:
              columns: 9
              rows: 1
            icon: mdi:solar-power
          - type: clock
            card_mod:
              style: |
                :host { }
                ha-card {
                  background: none;
                  border: none;
                  padding: 10px 0 0 0;
                  text-align: right;
                }
            grid_options:
              columns: 3
              rows: 1
        column_span: 2
      - type: grid
        cards:
          - type: custom:mushroom-entity-card
            entity: sensor.solcast_pv_forecast_forecast_this_hour
            grid_options:
              columns: 3
              rows: 1
            fill_container: true
            layout: horizontal
            name: This Hour
            icon: none
            icon_type: none
            card_mod:
              style: |
                ha-card {
                  background: none;
                  border: none;
                }
          - type: custom:mushroom-entity-card
            grid_options:
              columns: 3
              rows: 1
            fill_container: false
            layout: horizontal
            name: Next Hour
            icon: mdi:solar-power
            icon_type: none
            entity: sensor.solcast_pv_forecast_forecast_next_hour
            card_mod:
              style: |
                ha-card {
                  background: none;
                  border: none;
                }
          - type: custom:mushroom-entity-card
            fill_container: true
            layout: horizontal
            name: Remaining Today
            icon: none
            icon_type: none
            grid_options:
              columns: 3
              rows: 1
            entity: sensor.solcast_pv_forecast_forecast_remaining_today
            card_mod:
              style: |
                ha-card {
                  background: none;
                  border: none;
                }
          - type: custom:mushroom-entity-card
            grid_options:
              columns: 3
              rows: 1
            fill_container: true
            layout: horizontal
            name: Today
            icon: none
            icon_type: none
            entity: sensor.solcast_pv_forecast_forecast_today
            card_mod:
              style: |
                ha-card {
                  background: none;
                  border: none;
                }
          - type: custom:mushroom-entity-card
            entity: sensor.solcast_pv_forecast_forecast_tomorrow
            grid_options:
              columns: 6
              rows: 1
            fill_container: true
            name: Tomorrow
            icon: none
            icon_type: none
            card_mod:
              style: |
                ha-card {
                  background: none;
                  border: none;
                }
        column_span: 2
      - type: grid
        cards:
          - type: custom:power-flow-card-plus
            entities:
              battery:
                entity:
                  '0': b
                  '1': i
                  '2': 'n'
                  '3': a
                  '4': r
                  '5': 'y'
                  '6': _
                  '7': s
                  '8': e
                  '9': 'n'
                  '10': s
                  '11': o
                  '12': r
                  '13': .
                  '14': e
                  '15': s
                  '16': 'y'
                  '17': _
                  '18': s
                  '19': u
                  '20': 'n'
                  '21': h
                  '22': o
                  '23': m
                  '24': e
                  '25': _
                  '26': b
                  '27': a
                  '28': t
                  '29': t
                  '30': e
                  '31': r
                  '32': 'y'
                  '33': _
                  '34': a
                  '35': c
                  '36': t
                  '37': i
                  '38': v
                  '39': e
                  consumption: sensor.esy_sunhome_battery_export
                  production: sensor.esy_sunhome_battery_import
                state_of_charge: sensor.esy_sunhome_battery_state_of_charge
              grid:
                entity:
                  '0': b
                  '1': i
                  '2': 'n'
                  '3': a
                  '4': r
                  '5': 'y'
                  '6': _
                  '7': s
                  '8': e
                  '9': 'n'
                  '10': s
                  '11': o
                  '12': r
                  '13': .
                  '14': e
                  '15': s
                  '16': 'y'
                  '17': _
                  '18': s
                  '19': u
                  '20': 'n'
                  '21': h
                  '22': o
                  '23': m
                  '24': e
                  '25': _
                  '26': g
                  '27': r
                  '28': i
                  '29': d
                  '30': _
                  '31': a
                  '32': c
                  '33': t
                  '34': i
                  '35': v
                  '36': e
                  consumption: sensor.esy_sunhome_grid_import
                  production: sensor.esy_sunhome_grid_export
                secondary_info: {}
              solar:
                display_zero_state: true
                secondary_info: {}
                entity: sensor.esy_sunhome_pv_power
              home:
                secondary_info: {}
                use_metadata: false
                override_state: false
                subtract_individual: true
                entity: sensor.esy_sunhome_load_power
              fossil_fuel_percentage:
                secondary_info: {}
            clickable_entities: false
            display_zero_lines:
              mode: hide
              transparency: 50
              grey_color:
                - 189
                - 189
                - 189
            use_new_flow_rate_model: true
            w_decimals: 0
            kw_decimals: 1
            min_flow_rate: 0.75
            max_flow_rate: 6
            max_expected_power: 2000
            min_expected_power: 0.01
            watt_threshold: 1000
            transparency_zero_lines: 0
            sort_individual_devices: false
            dashboard_link: ''
          - type: energy-distribution
        column_span: 2
      - type: grid
        cards:
          - type: custom:apexcharts-card
            experimental:
              color_threshold: true
            graph_span: 24h
            span:
              start: minute
            header:
              show: true
              title: Amber Electricty Forecast
              show_states: false
              colorize_states: true
            series:
              - entity: sensor.home_general_forecast
                float_precision: 2
                color_threshold:
                  - value: 0
                    color: cyan
                  - value: 0.16
                    color: green
                  - value: 0.25
                    color: yellow
                  - value: 0.4
                    color: red
                name: price kwh
                data_generator: |
                  return entity.attributes.forecasts.map((entry) => {
                    return [new Date(entry.start_time), entry.per_kwh];
                  });
            yaxis:
              - min: 0
                max: ~0.5
                decimals: 2
                apex_config:
                  forceNiceScale: true
            apex_config:
              stroke:
                width: 2.5
              grid:
                show: true
                borderColor: '#333'
                strokeDashArray: 1
          - type: custom:apexcharts-card
            experimental:
              color_threshold: true
            graph_span: 24h
            span:
              start: minute
            header:
              show: true
              title: Amber Feed-In Forecast
              show_states: false
              colorize_states: true
            series:
              - entity: sensor.home_feed_in_forecast
                float_precision: 2
                color_threshold:
                  - value: 0
                    color: red
                  - value: 0.16
                    color: yellow
                  - value: 0.25
                    color: cyan
                  - value: 0.5
                    color: green
                name: price kwh
                data_generator: |
                  return entity.attributes.forecasts.map((entry) => {
                    return [new Date(entry.start_time), entry.per_kwh];
                  });
            yaxis:
              - min: ~0
                max: ~0.5
                decimals: 2
                apex_config:
                  forceNiceScale: true
            apex_config:
              stroke:
                width: 2.5
              grid:
                show: true
                borderColor: '#333'
                strokeDashArray: 1
        column_span: 2
      - type: grid
        cards:
          - type: energy-sankey
            grid_options:
              columns: 24
              rows: 4
        column_span: 2
      - type: grid
        cards:
          - type: custom:apexcharts-card
            layout_options:
              grid_columns: 24
            experimental:
              disable_config_validation: true
            graph_span: 24h
            span:
              end: day
              offset: +1h
            yaxis:
              - decimals: 2
                apex_config:
                  forceNiceScale: true
                  labels:
                    formatter: |
                      EVAL:function(value) {
                        if (value.toString().length > 6)
                          return '0.00';
                        return Math.abs(value).toFixed(2);
                      }
            apex_config:
              annotations:
                position: front
              chart:
                height: 400
              stroke:
                width: 2
              grid:
                show: false
              xaxis:
                lines:
                  show: false
                axisBorder:
                  show: false
              yaxis:
                axisBorder:
                  show: false
              legend:
                show: false
            all_series_config:
              extend_to: now
              float_precision: 2
            stacked: true
            series:
              - entity: sensor.half_hour_max_import
                type: column
                name: Import from Grid
                color: '#656567'
                show:
                  datalabels: false
                  extremas: false
                invert: true
                group_by:
                  func: max
                  duration: 30m
                transform: 'return x == 0.0 ? null : x;'
              - entity: sensor.half_hour_max_consumption
                type: column
                name: Consumption
                color: '#d67629'
                show:
                  datalabels: false
                  extremas: false
                invert: true
                group_by:
                  func: last
                  duration: 30m
                transform: 'return x == 0.0 ? null : x;'
              - entity: sensor.half_hour_max_production
                type: column
                name: Production
                color: '#6eb4dc'
                show:
                  datalabels: false
                  extremas: false
                invert: false
                group_by:
                  func: last
                  duration: 30m
                transform: 'return x == 0.0 ? null : x;'
              - entity: sensor.half_hour_max_export
                type: column
                name: Export to Grid
                color: '#656567'
                show:
                  datalabels: false
                  extremas: false
                invert: false
                group_by:
                  func: last
                  duration: 30m
                transform: 'return x == 0.0 ? null : x;'
            card_mod:
              style: |
                :host {
                  width: 100%
                }
                ha-card {
                  width: 100%;
                }
                .wrapper.with-header {
                  width: 100%;
                }
        column_span: 2
    header: {}
    cards: []
    badges:
      - type: custom:mushroom-template-badge
        content: '{{ ((25 * ((states(entity) | int)/100)) | float(0)) | round(1) }} kWh'
        color: |-
          {% set number = (states(entity) | int) %}
          {% if (number >= 70) %}
          green
          {% elif (number >= 40) %}
          yellow
          {% elif (number >= 30) %}
          orange
          {% else %}
          red
          {% endif %}
        label: Battery SoC - {{(states(entity) | int)}}%
        tap_action:
          action: navigate
          navigation_path: /config/devices/device/91b5a8d4f272ea50b568420b3e866baf
        entity: sensor.esy_sunhome_battery_state_of_charge
        icon: |-
          {% set number = (states(entity) | int) %}
          {% if (number >= 90) %}
          mdi:battery
          {% elif (number >= 80) %}
          mdi:battery-80
          {% elif (number >= 70) %}
          mdi:battery-70
          {% elif (number >= 60) %}
          mdi:battery-60
          {% elif (number >= 50) %}
          mdi:battery-50
          {% elif (number >= 40) %}
          mdi:battery-40
          {% elif (number >= 30) %}
          mdi:battery-30
          {% elif (number >= 20) %}
          mdi:battery-20
          {% elif (number >= 10) %}
          mdi:battery-10
          {% elif (number >= 0) %}
          mdi:battery-outline
          {% else %}
          mdi:battery
          {% endif %}
      - type: entity
        show_name: true
        show_state: true
        show_icon: true
        entity: sensor.esy_sunhome_pv_power
        name: 'Production '
        color: accent
      - type: entity
        show_name: true
        show_state: true
        show_icon: true
        entity: sensor.esy_sunhome_load_power
        name: Consumption
      - type: custom:mushroom-template-badge
        icon: mdi:currency-usd
        label: Daily Cost
        content: ${{ states.sensor.daily_cost.state | float | round(2) }}
        entity: sensor.daily_cost
        color: |-
          {% set rate=states(entity) | float %}
          {% if rate > 1 %}
          red
          {% elif rate < 0 %}
          green
          {% else %}
          yellow
          {% endif %}
        double_tap_action:
          action: url
          url_path: app://com.amberelectric.customerportal
        hold_action:
          action: url
          url_path: app://com.amberelectric.customerportal
        tap_action:
          action: more-info
      - type: custom:mushroom-template-badge
        icon: mdi:currency-usd
        label: Monthly Cost
        content: ${{ states.sensor.monthly_cost.state | float | round(2) }}
        color: |-
          {% set rate=states(entity) | float %}
          {% if rate > 20 %}
          red
          {% elif rate < 0 %}
          green
          {% else %}
          yellow
          {% endif %}
        entity: sensor.monthly_cost
        double_tap_action:
          action: url
          url_path: app://com.amberelectric.customerportal
        hold_action:
          action: url
          url_path: app://com.amberelectric.customerportal
      - type: custom:mushroom-template-badge
        content: >-
          {{ (states.sensor.current_charge.state  | float(0) * 100) | round(1)
          }}c / kWh
        entity: sensor.current_rate
        color: |-
          {% set rate=states(entity) %}
          {# [ negative, extremelyLow, veryLow, low, neutral, high, spike ] #}
          {% if rate == 'Negative' %}
          green
          {% elif rate == 'Extremely Low' %}
          green
          {% elif rate == 'Very Low' %}
          green
          {% elif rate == 'Low' %}
          yellow
          {% elif rate == 'Neutral' %}
          red
          {% elif rate == 'High' %}
          red
          {% elif rate == 'Spike' %}
          red
          {% else %}
          white
          {% endif %}
        label: 'Import - {{states.sensor.current_rate.state }} '
        double_tap_action:
          action: url
          url_path: app://com.amberelectric.customerportal
        hold_action:
          action: url
          url_path: app://com.amberelectric.customerportal
        icon: mdi:transmission-tower-import
      - type: custom:mushroom-template-badge
        content: >-
          {{ (states.number.current_export_charge.state | float(0) * 100) |
          round(1) }}c / kWh
        color: |-
          {% set rate=states(entity) %}
          {# [ negative, extremelyLow, veryLow, low, neutral, high, spike ] #}
          {% if rate == 'Negative' %}
          red
          {% elif rate == 'Extremely Low' %}
          red
          {% elif rate == 'Very Low' %}
          green
          {% elif rate == 'Low' %}
          yellow
          {% elif rate == 'Neutral' %}
          yellow
          {% elif rate == 'High' %}
          green
          {% elif rate == 'Spike' %}
          green
          {% else %}
          white
          {% endif %}
        label: 'Export - {{states.sensor.current_export_rate.state}} '
        double_tap_action:
          action: url
          url_path: app://com.amberelectric.customerportal
        hold_action:
          action: url
          url_path: app://com.amberelectric.customerportal
        entity: sensor.current_export_rate
        icon: mdi:transmission-tower-export
    max_columns: 2
    dense_section_placement: false
{% endraw %}