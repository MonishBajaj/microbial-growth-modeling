
# Command-line demo of the older model (microbial_growth_model.py) and meater_api.py.
# use_real_meater() has a hardcoded MEATER login in the source. Replace that
# email and password before you run it, and do not share the file with the
# login still filled in. The web app does not import this file.
# Example usage of the microbial growth model with MEATER API
from microbial_growth_model import MicrobialGrowthModel
from meater_api import MeaterAPI
import numpy as np
import matplotlib.pyplot as plt

def main():
    """Example usage of the complete system"""

    # Option 1: Use with real MEATER device
    def use_real_meater():
        # Initialize API
        meater = MeaterAPI()

        # Authenticate (replace with your credentials)
        success = meater.authenticate("roysid675@gmail.com", "Babansid@123")
        if not success:
            return

        # Collect temperature data
        temp_data = meater.collect_temperature_data(
            duration_hours=2,
            interval_minutes=5
        )

        if temp_data is None:
            return

        # Run growth simulation with ambient temperature
        model = MicrobialGrowthModel()
        results = model.simulate_growth(
            temp_data['time_hours'],
            temp_data['ambient_temperature']
        )

        # Plot results
        plot_results(results, temp_data)

    # Option 2: Use with sample data (for testing)
    def use_sample_data():
        # Generate sample temperature data (sinusoidal like original MATLAB)
        time_hours = np.arange(0, 51, 1)  # 0 to 50 hours
        temperatures = 25 + 10 * np.sin(2 * np.pi * time_hours / 6)

        # Run simulation
        model = MicrobialGrowthModel()
        results = model.simulate_growth(time_hours, temperatures)

        # Plot results
        plot_results(results)

        print(f"Final population: {results['population'][-1]:.2f} Log CFU/g")

        return results

    def plot_results(results, temp_data=None):
        """Plot the simulation results"""
        fig, ax1 = plt.subplots(figsize=(12, 8))

        # Plot population
        ax1.plot(results['time'], results['population'], 'b-', linewidth=2, label='Predicted Population')
        ax1.set_xlabel('Time (h)', fontsize=14)
        ax1.set_ylabel('Pseudomonas population (Log CFU/g)', fontsize=14, color='blue')
        ax1.set_ylim(0, 10)
        ax1.tick_params(axis='y', labelcolor='blue')

        # Add experimental data points (from original MATLAB)
        Tv = np.array([0, 2, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48])
        Yv = np.array([2.514, 2.874, 3.239, 5.123, 5.096, 6.327, 7.314, 7.969, 
                       8.048, 7.856, 8.124, 8.233, 8.093, 8.206])
        Err = np.array([0.229, 0.047, 0.282, 0.174, 0.143, 0.036, 0.136, 0.324,
                        0.203, 0.017, 0.026, 0.008, 0.028, 0.110])

        ax1.errorbar(Tv, Yv, yerr=Err, fmt='ro', capsize=5, capthick=2, 
                    markersize=6, label='Experimental Data')
        ax1.legend()

        # Plot temperature on second y-axis
        ax2 = ax1.twinx()
        ax2.plot(results['time'], results['temperature'], 'r--', linewidth=2, label='Temperature')
        ax2.set_ylabel('Temperature (°C)', fontsize=14, color='red')
        ax2.set_ylim(10, 40)
        ax2.tick_params(axis='y', labelcolor='red')

        ax1.grid(True, alpha=0.3)
        ax1.set_title('Microbial Growth Model Results - Python Implementation', fontsize=16)

        plt.tight_layout()
        plt.savefig('microbial_growth_results.png', dpi=300, bbox_inches='tight')
        plt.show()

    # Run the sample data example
    print("Running microbial growth simulation with sample data...")
    results = use_sample_data()

    # Uncomment to use real MEATER device:
    # use_real_meater()

if __name__ == "__main__":
    main()
