To accurately estimate the bypass state of your Zehnder ComfoAir Q350, we treat the unit as a "mixing valve" that interpolates between two physical states: **Maximum Heat Recovery** and **Residual Heat Recovery** (the leakage/housing gain that happens even when bypass is "100% open").

The following approach provides both the Temperature-only method and the Enthalpy-based method for ERV cores.

* * * *

### 1\. The Core Logic: Linear Interpolation

The bypass percentage $B$ is not a direct measurement of temperature, but a measurement of **efficiency degradation**.

-   **State 0 (Bypass 0%):** The unit operates at its maximum calibrated efficiency ($\\eta\_{max}$).

-   **State 1 (Bypass 100%):** The unit operates at its minimum residual efficiency ($\\eta\_{min}$).

The formula finds where the current efficiency ($\\eta\_{curr}$) sits on the line between these two points:

$$B = \frac{\eta_{max} - \eta_{curr}}{\eta_{max} - \eta_{min}}$$

* * * *

### 2\. Parameter Definitions

| **Parameter** | **Description** | **Units** |
| --- |  --- |  --- |
| $T\_{OA} / RH\_{OA}$ | **Outdoor Air:** Intake before the ERV core. | $^\\circ$C / % |
| --- |  --- |  --- |
| $T\_{SA} / RH\_{SA}$ | **Supply Air:** Fresh air after the ERV core, going to rooms. | $^\\circ$C / % |
| $T\_{RA} / RH\_{RA}$ | **Return Air:** Stale air from rooms before the ERV core. | $^\\circ$C / % |
| $P\_{atm}$ | **Atmospheric Pressure:** Local pressure (standard is 101.325). | kPa |
| $\\eta\_{max}$ | **Calibrated Max Efficiency:** Efficiency when bypass is known 0%. | Decimal (0-1) |
| $\\eta\_{min}$ | **Calibrated Min Efficiency:** Residual "efficiency" when bypass is 100%. | Decimal (0-1) |

* * * *

### 3\. Step 1: Calculating Enthalpy ($h$)

To calculate the total energy in the air (Sensible + Latent), we must find the Specific Enthalpy ($h$).

1.  **Saturation Vapor Pressure ($p_s$):**

    $$p_s = 0.61078 \cdot \exp\left(\frac{17.27 \cdot T}{T + 237.3}\right)$$

2.  **Actual Vapor Pressure ($p_v$):**

    $$p_v = p_s \cdot \frac{RH}{100}$$

3.  **Humidity Ratio ($w$):** (kg of water per kg of dry air)

    $$w = 0.622 \cdot \frac{p_v}{P_{atm} - p_v}$$

4.  **Specific Enthalpy ($h$):** (in kJ/kg)

    $$h = 1.006 \cdot T + w \cdot (2501 + 1.86 \cdot T)$$

* * * *

### 4\. Step 2: Calculating Efficiency ($\\eta$)

You can calculate efficiency using either Temperature ($T$) or Enthalpy ($h$).

-   **Temperature Efficiency:** $\eta_{T} = \frac{T_{SA} - T_{OA}}{T_{RA} - T_{OA}}$

-   **Enthalpy Efficiency:** $\eta_{h} = \frac{h_{SA} - h_{OA}}{h_{RA} - h_{OA}}$

* * * *

### 5\. Pseudo-Code Implementation

Python

```
# Constants for Enthalpy Physics
C_P_AIR = 1.006     # Specific heat of dry air
H_FG = 2501         # Latent heat of vaporization
C_P_VAPOR = 1.86    # Specific heat of water vapor

def get_bypass_range(T_oa, RH_oa, T_sa, RH_sa, T_ra, RH_ra, P_atm, eff_max, eff_min, use_enthalpy=True):

    # Internal function to calculate Enthalpy
    def calculate_h(temp, rh, press):
        p_s = 0.61078 * exp((17.27 * temp) / (temp + 237.3))
        p_v = p_s * (rh / 100.0)
        w = 0.622 * (p_v / (press - p_v))
        return (C_P_AIR * temp) + w * (H_FG + C_P_VAPOR * temp)

    # 1. Determine Current Efficiency
    if use_enthalpy:
        h_oa = calculate_h(T_oa, RH_oa, P_atm)
        h_sa = calculate_h(T_sa, RH_sa, P_atm)
        h_ra = calculate_h(T_ra, RH_ra, P_atm)

        # Guard against division by zero (if indoor/outdoor energy is identical)
        if abs(h_ra - h_oa) < 0.5: return "Inconclusive (Delta too small)"
        eff_curr = (h_sa - h_oa) / (h_ra - h_oa)
    else:
        if abs(T_ra - T_oa) < 0.5: return "Inconclusive (Delta too small)"
        eff_curr = (T_sa - T_oa) / (T_ra - T_oa)

    # 2. Calculate Raw Bypass Fraction
    # This maps eff_curr onto the range [eff_min, eff_max]
    b_raw = (eff_max - eff_curr) / (eff_max - eff_min)

    # 3. Clamp B between 0 and 1 to handle measurement noise/efficiency overshoot
    b_clamped = max(0, min(1, b_raw))

    # 4. Convert to Range String
    if b_clamped == 0:
        return "0 (closed)"
    elif 0 < b_clamped <= 0.25:
        return "1-25"
    elif 0.25 < b_clamped <= 0.50:
        return "25-50"
    elif 0.50 < b_clamped <= 0.75:
        return "50-75"
    else:
        return "75-100"

```

### Explanation of Variables in Pseudo-code:

-   **`p_s` (Saturation Vapor Pressure):** The maximum pressure water vapor could exert at that temperature.

-   **`p_v` (Actual Vapor Pressure):** The actual pressure based on the humidity percentage.

-   **`w` (Humidity Ratio):** The physical mass of water suspended in the air. This is crucial for ERV because it doesn't change unless condensation or active exchange occurs.

-   **`eff_curr`:** The percentage of the available energy "gap" between inside and outside that the unit successfully transferred to the supply air.

-   **`b_raw`:** The linear position of the current efficiency relative to your best and worst case scenarios. If `eff_curr` is closer to `eff_max`, the bypass is mostly closed.

-   **`b_clamped`:** Prevents the formula from returning "-5%" or "110%" if the sensors drift or your calibrated efficiency is slightly off.
