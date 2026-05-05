import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'de.bos.marschplan',
  appName: 'MarschPlan',
  webDir: 'build',
  server: {
    androidScheme: 'https',
  },
  plugins: {
    Geolocation: {
      // iOS: Hintergrund-Tracking erfordert NSLocationAlwaysAndWhenInUseUsageDescription
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
  },
};

export default config;
