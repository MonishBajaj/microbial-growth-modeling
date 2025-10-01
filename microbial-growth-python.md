# Microbial Growth Modeling with MEATER Plus API Integration

## Complete Python Implementation

This Python implementation replaces the MATLAB code for dynamic microbial growth modeling by integrating with the MEATER Plus API for real-time temperature input.

## Key Features

### 1. **MicrobialGrowthModel Class**
- Implements the Baranyi-Roberts growth model
- Uses 4th-order Runge-Kutta numerical integration
- Handles temperature-dependent growth rate calculations
- Supports both physiological state (Q) and population (y) dynamics

### 2. **MeaterAPI Class**
- Authenticates with MEATER Cloud REST API
- Retrieves real-time temperature data from connected probes
- Supports both internal and ambient temperature monitoring
- Implements rate limiting and error handling

### 3. **MicrobialGrowthAnalyzer Class**
- Integrates the growth model with MEATER API
- Provides accuracy metrics calculation
- Generates comprehensive visualizations
- Supports both real-time and sample data analysis

## Installation Requirements

```python
pip install numpy scipy matplotlib pandas requests
```

## Usage Examples

### Real MEATER Device Integration
```python
from microbial_growth_analyzer import MicrobialGrowthAnalyzer

# Initialize analyzer
analyzer = MicrobialGrowthAnalyzer()

# Use real MEATER device
results = analyzer.analyze_with_meater_data(
    email="your_email@example.com",
    password="your_password", 
    duration_hours=2,
    interval_minutes=5
)

# Plot results
fig = analyzer.plot_results(results)
```

### Sample Data Testing
```python
# Test with sample sinusoidal temperature data
results = analyzer.analyze_with_sample_data(duration_hours=50)

# Calculate accuracy metrics
accuracy = analyzer.calculate_accuracy_metrics(
    results['population'], observed_times, observed_values, observed_errors
)
```

### Custom Temperature Profiles
```python
# Use custom temperature data
model = MicrobialGrowthModel()
results = model.simulate_growth(time_hours, custom_temperatures)
```

## Model Parameters

### Primary Model (Baranyi-Roberts)
- `y0 = 2.51`: Initial population (Log CFU/g)
- `ymax = 8.0`: Maximum population (Log CFU/g) 
- `h0 = 1.07`: Initial physiological state parameter

### Secondary Model (Temperature Dependence)
- `Tmin = -1.6081°C`: Minimum growth temperature
- `Tmax = 35.1581°C`: Maximum growth temperature
- `a = 0.0005`: Growth rate coefficient
- `b = 4.7509`: Temperature sensitivity parameter

## MEATER API Integration

### Authentication
```python
meater = MeaterAPI()
success = meater.authenticate(email, password)
```

### Data Collection
```python
temp_data = meater.collect_temperature_data(
    device_id=None,  # Auto-detect first available
    duration_hours=2,
    interval_minutes=1
)
```

### API Endpoints Used
- `POST /login`: Authentication with JWT tokens
- `GET /devices`: List all connected devices
- `GET /devices/{id}`: Get specific device data

## Key Differences from MATLAB

### Improvements
1. **Real-time data**: Uses MEATER API instead of predetermined temperature profile
2. **Object-oriented design**: Modular, reusable classes
3. **Error handling**: Robust API error management
4. **Flexibility**: Supports multiple data sources and analysis modes

### Mathematical Equivalence
- Uses SciPy's `CubicSpline` equivalent to MATLAB's `spline()` function
- Implements identical Runge-Kutta 4th order algorithm
- Maintains same Baranyi-Roberts model formulation
- Preserves accuracy metric calculations (Af, Bf)

## Output and Visualization

### Simulation Results
```python
{
    'time': array,                    # Time points (hours)
    'temperature': array,             # Temperature profile (°C)
    'population': array,              # Predicted population (Log CFU/g)
    'physiological_state': array,     # Q values
    'growth_rate': array,            # μmax values
    'time_fine': array               # Fine time grid for RK4
}
```

### Accuracy Metrics
```python
{
    'accuracy_factor': float,         # Af = 10^(Σ|log10(obs/pred)|/n)
    'bias_factor': float,            # Bf = 10^(Σlog10(obs/pred)/n)
    'predicted_at_observations': array,
    'residuals': array
}
```

## Error Handling

### API Errors
- Authentication failures
- Device connection issues
- Rate limiting (max 60 requests/60 seconds)
- Network timeouts

### Model Errors
- Temperature out of range handling
- Numerical stability checks
- Data interpolation validation

## Rate Limiting

MEATER API limits:
- **Recommended**: 2 requests per 60 seconds
- **Maximum**: 60 requests per 60 seconds

The implementation automatically handles these limits during data collection.

## Dependencies

### Core Libraries
- `numpy`: Numerical computations
- `scipy`: Interpolation and scientific functions
- `matplotlib`: Visualization
- `pandas`: Data handling (optional)
- `requests`: HTTP API calls

### MEATER Requirements
- MEATER Plus, MEATER Block, or MEATER Pro device
- Active MEATER Cloud account
- Device connected to WiFi/Bluetooth with cloud sync

## File Structure

```
microbial_growth_modeling/
├── microbial_growth_model.py      # Core growth model
├── meater_api.py                  # MEATER API client
├── growth_analyzer.py             # Integration class
├── examples/
│   ├── real_time_analysis.py      # Real MEATER usage
│   ├── sample_data_test.py        # Testing example
│   └── custom_temperature.py      # Custom profiles
└── README.md                      # This file
```

## Future Enhancements

1. **Multiple probe support**: Handle multiple MEATER devices simultaneously
2. **Data logging**: Persistent storage of temperature and growth data
3. **Web interface**: Real-time dashboard for monitoring
4. **Advanced models**: Support for additional microbial growth models
5. **Machine learning**: Predictive model improvements based on historical data

This implementation provides a complete replacement for the MATLAB system while adding real-time temperature monitoring capabilities through the MEATER Plus API integration.