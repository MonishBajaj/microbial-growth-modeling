# Enhanced Microbial Growth Analysis with Real-time MEATER Temperature Display
import numpy as np
import matplotlib.pyplot as plt
import time
from datetime import datetime

# Import the enhanced MEATER API and original growth model
from enhanced_meater_api import EnhancedMeaterAPI
from corrected_microbial_growth_model import CorrectedMicrobialGrowthModel

class EnhancedMicrobialGrowthAnalyzer:
    """Enhanced analyzer with real-time temperature monitoring and connection testing"""

    def __init__(self):
        """Initialize with enhanced MEATER API and growth model"""
        self.meater_api = EnhancedMeaterAPI()
        self.model = CorrectedMicrobialGrowthModel()

    def test_meater_connection(self, email=None, password=None):
        """
        Test MEATER device connection before running full analysis

        Parameters:
        email: MEATER account email
        password: MEATER account password

        Returns:
        bool: True if connection successful
        """
        print("\n" + "="*60)
        print("🧪 MEATER CONNECTION TEST")
        print("="*60)

        if not email or not password:
            print("❌ Email and password required for connection test")
            return False

        # Step 1: Authentication
        success = self.meater_api.authenticate(email, password)
        if not success:
            return False

        # Step 2: Device detection
        devices = self.meater_api.get_devices()
        if not devices:
            return False

        # Step 3: Connection test
        connection_ok = self.meater_api.test_connection()

        if connection_ok:
            print("\n🎉 MEATER device is ready for data collection!")
            return True
        else:
            print("\n❌ MEATER device connection failed")
            print("\n🔧 Troubleshooting tips:")
            print("   - Ensure MEATER is charged and powered on")
            print("   - Check WiFi/Bluetooth connection")
            print("   - Verify device is paired in MEATER app")
            print("   - Try restarting the MEATER app")
            return False

    def analyze_with_realtime_meater(self, email, password, device_id=None, 
                                   duration_hours=0.1, interval_seconds=2):
        """
        Analyze microbial growth with real-time MEATER temperature display

        Parameters:
        email: MEATER account email
        password: MEATER account password
        device_id: Specific device ID (optional)
        duration_hours: Data collection duration (default: 6 minutes for testing)
        interval_seconds: Temperature reading interval (minimum 2 seconds)

        Returns:
        dict: Analysis results or error message
        """
        print("\n" + "="*60)
        print("🔬 REAL-TIME MICROBIAL GROWTH ANALYSIS")
        print("="*60)

        # Test connection first
        if not self.test_meater_connection(email, password):
            return {"error": "MEATER connection test failed"}

        print("\n📡 Starting real-time temperature data collection...")
        print("   💡 You'll see live temperature readings below")

        # Collect temperature data with real-time display
        temp_data = self.meater_api.collect_temperature_data_realtime(
            device_id=device_id,
            duration_hours=duration_hours,
            interval_seconds=max(interval_seconds, 2)  # Ensure minimum 2 seconds
        )

        if temp_data is None:
            return {"error": "Failed to collect temperature data from MEATER device"}

        print(f"\n🧮 Running microbial growth simulation...")
        print(f"   Using {len(temp_data['time_hours'])} temperature readings")
        print(f"   Temperature data from device: {temp_data['device_id'][:8]}...")

        # Run growth simulation using ambient temperature
        results = self.model.simulate_growth(
            temp_data['time_hours'], 
            temp_data['ambient_temperature']
        )

        # Add MEATER data to results
        results['meater_data'] = temp_data
        results['data_source'] = 'MEATER_REALTIME'

        print(f"✅ Analysis complete!")
        print(f"   Final population: {results['population'][-1]:.2f} Log CFU/g")
        print(f"   Temperature range: {np.min(temp_data['ambient_temperature']):.1f}°C to {np.max(temp_data['ambient_temperature']):.1f}°C")
        print(f"   Total MEATER readings: {temp_data['readings_count']}")

        return results

    def quick_meater_test(self, email, password, test_duration_seconds=30):
        """
        Quick test to verify MEATER is working and showing live temperatures

        Parameters:
        email: MEATER account email
        password: MEATER account password
        test_duration_seconds: How long to display live temperatures

        Returns:
        bool: True if test successful
        """
        print("\n" + "="*60)
        print(f"⚡ QUICK MEATER TEST ({test_duration_seconds} seconds)")
        print("="*60)
        print("This will show live temperature readings from your MEATER device")

        # Authenticate
        if not self.meater_api.authenticate(email, password):
            return False

        # Get devices
        devices = self.meater_api.get_devices()
        if not devices or not devices.get('data', {}).get('devices'):
            print("❌ No devices available for testing")
            return False

        device_id = devices['data']['devices'][0]['id']
        print(f"\n📱 Testing device: {device_id}")
        print(f"🕐 Displaying live temperatures for {test_duration_seconds} seconds...")
        print("   💡 Watch below for real-time temperature updates")
        print("\n🔴 LIVE TEMPERATURES:")
        print("-" * 60)

        end_time = time.time() + test_duration_seconds
        reading_count = 0
        temperatures = []

        try:
            while time.time() < end_time:
                device_data = self.meater_api.get_device_realtime(device_id)

                if device_data and 'data' in device_data and 'temperature' in device_data['data']:
                    reading_count += 1
                    temp_data = device_data['data']['temperature']
                    temperatures.append({
                        'internal': temp_data.get('internal', 0),
                        'ambient': temp_data.get('ambient', 0)
                    })

                time.sleep(2)  # 2-second intervals for testing

        except KeyboardInterrupt:
            print("\n\n⏹️  Test stopped by user")

        print(f"\n\n" + "="*60)
        print(f"✅ Quick test completed!")
        print(f"   Total readings: {reading_count}")
        print(f"   MEATER connection: {'✅ WORKING' if reading_count > 0 else '❌ FAILED'}")

        if temperatures:
            avg_internal = np.mean([t['internal'] for t in temperatures])
            avg_ambient = np.mean([t['ambient'] for t in temperatures])
            print(f"   Average internal temp: {avg_internal:.1f}°C")
            print(f"   Average ambient temp: {avg_ambient:.1f}°C")

        return reading_count > 0

def run_sample_data_analysis():
    """Run analysis with sample data (no MEATER required)"""

    print("\n" + "="*60)
    print("📊 SAMPLE DATA ANALYSIS (No MEATER Required)")
    print("="*60)

    print("Generating sample temperature data...")

    # Generate sample data matching original MATLAB pattern
    time_hours = np.arange(0, 51, 1)
    temperatures = 25 + 10 * np.sin(2 * np.pi * time_hours / 6)

    # Initialize model and run simulation
    model = CorrectedMicrobialGrowthModel()
    results = model.simulate_growth(time_hours, temperatures)

    results['data_source'] = 'SAMPLE_DATA'

    print(f"✅ Sample analysis complete!")
    print(f"   Final population: {results['population'][-1]:.2f} Log CFU/g")
    print(f"   Temperature range: {np.min(temperatures):.1f}°C to {np.max(temperatures):.1f}°C")

    # Plot results
    plot_results(results)

    return results

def plot_results(results):
    """Enhanced plotting function with data source information"""

    fig, ax1 = plt.subplots(figsize=(12, 8))

    # Plot population
    ax1.plot(results['time'], results['population'], 'b-', linewidth=2, label='Predicted Population')
    ax1.set_xlabel('Time (h)', fontsize=14)
    ax1.set_ylabel('Pseudomonas population (Log CFU/g)', fontsize=14, color='blue')
    ax1.set_ylim(0, 10)
    ax1.tick_params(axis='y', labelcolor='blue')

    # Add experimental data points from original MATLAB
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
    line_style = '-' if results.get('data_source') == 'MEATER_REALTIME' else '--'
    ax2.plot(results['time'], results['temperature'], f'r{line_style}', linewidth=2, label='Temperature')
    ax2.set_ylabel('Temperature (°C)', fontsize=14, color='red')
    ax2.set_ylim(10, 40)
    ax2.tick_params(axis='y', labelcolor='red')

    # Add data source info to title
    data_source = results.get('data_source', 'UNKNOWN')
    if data_source == 'MEATER_REALTIME':
        device_info = ""
        if 'meater_data' in results:
            device_id = results['meater_data'].get('device_id', '')[:8]
            readings = results['meater_data'].get('readings_count', 0)
            device_info = f" - Device: {device_id} ({readings} readings)"
        title = f'Microbial Growth Model - Real-time MEATER Data{device_info}'
    else:
        title = f'Microbial Growth Model - {data_source.replace("_", " ").title()}'

    ax1.set_title(title, fontsize=16)
    ax1.grid(True, alpha=0.3)

    plt.tight_layout()

    # Save with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f'microbial_growth_results_{timestamp}.png'
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    print(f"\n📊 Plot saved as: {filename}")

    plt.show()

def main():
    """
    Enhanced main function with multiple testing options
    """

    # =================================================================
    # IMPORTANT: UPDATE THESE WITH YOUR ACTUAL MEATER CREDENTIALS
    # =================================================================
    MEATER_EMAIL = "roysid675@gmail.com"  # 👈 CHANGE THIS
    MEATER_PASSWORD = "Babansid@123"         # 👈 CHANGE THIS
    # =================================================================

    print("\n" + "="*70)
    print("🔬 ENHANCED MICROBIAL GROWTH ANALYZER WITH MEATER INTEGRATION")
    print("="*70)
    print("This tool analyzes microbial growth using temperature data from MEATER devices")

    # Check if credentials are set
    if MEATER_EMAIL == "your_email@example.com":
        print("\n⚠️  MEATER CREDENTIALS NOT SET!")
        print("   Please update MEATER_EMAIL and MEATER_PASSWORD in the code")
        print("   with your actual MEATER Cloud account details")
        print("\n🔄 Running with sample data instead...")
        print("\nPress Enter to continue...")
        input()
        run_sample_data_analysis()
        return

    # Initialize analyzer
    analyzer = EnhancedMicrobialGrowthAnalyzer()

    print("\n" + "="*60)
    print("🎯 SELECT ANALYSIS MODE:")
    print("="*60)
    print("1. 🧪 Quick Connection Test (30 seconds)")
    print("   - Tests if MEATER is connected and shows live temperatures")
    print("   - Perfect for verifying your device is working")
    print()
    print("2. 📊 Short Real-time Analysis (6 minutes)")
    print("   - Collects live temperature data and runs growth simulation")
    print("   - Shows real-time temperature readings in terminal")
    print()
    print("3. 🔬 Full Real-time Analysis (8 hours)")
    print("   - Complete analysis with extended temperature monitoring")
    print("   - Best for actual microbial growth studies")
    print()
    print("4. 📈 Sample Data Analysis (no MEATER needed)")
    print("   - Uses synthetic temperature data for testing")
    print("   - Matches original MATLAB results")

    try:
        choice = input("\nSelect option (1-4): ").strip()

        if choice == "1":
            print("\n🚀 Starting quick connection test...")
            print("   You should see live temperature readings appear below")
            success = analyzer.quick_meater_test(MEATER_EMAIL, MEATER_PASSWORD, 30)
            if success:
                print("\n🎉 Your MEATER device is working perfectly!")
                print("   Ready to run full analysis")
            else:
                print("\n❌ MEATER connection failed")
                print("   Check device status and try again")

        elif choice == "2":
            print("\n🚀 Starting short real-time analysis...")
            print("   Watch the terminal for live temperature readings!")
            results = analyzer.analyze_with_realtime_meater(
                MEATER_EMAIL, MEATER_PASSWORD, 
                duration_hours=0.1,  # 6 minutes
                interval_seconds=2   # Every 2 seconds
            )
            if "error" not in results:
                plot_results(results)
            else:
                print(f"\n❌ Analysis failed: {results['error']}")

        elif choice == "3":
            print("\n🚀 Starting full real-time analysis...")
            print("   This will collect data for 8 hours with live temperature display")
            confirm = input("   Continue? (y/N): ").strip().lower()
            if confirm == 'y':
                results = analyzer.analyze_with_realtime_meater(
                    MEATER_EMAIL, MEATER_PASSWORD,
                    duration_hours=8.0,  # 2 hours
                    interval_seconds=60  # 1 minute intervals
                )
                if "error" not in results:
                    plot_results(results)
                else:
                    print(f"\n❌ Analysis failed: {results['error']}")
            else:
                print("   Analysis cancelled")

        elif choice == "4":
            print("\n🚀 Running sample data analysis...")
            run_sample_data_analysis()

        else:
            print("❌ Invalid choice. Running sample data analysis...")
            run_sample_data_analysis()

    except KeyboardInterrupt:
        print("\n\n⏹️  Program interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nRunning sample data analysis as fallback...")
        run_sample_data_analysis()

if __name__ == "__main__":
    main()
