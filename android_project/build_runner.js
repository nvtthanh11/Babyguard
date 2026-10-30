const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { TwaGenerator, TwaManifest, ConsoleLog } = require('/Users/nvtthanh11/.npm/_npx/881cef4662d2c421/node_modules/@bubblewrap/core');

const projectDir = '/Volumes/SSD/WORK/baby_monitor/android_project';
const keystorePath = path.join(projectDir, 'babyguard.keystore');
const distDir = path.join(projectDir, 'dist');
const staticDir = '/Volumes/SSD/WORK/baby_monitor/static';

fs.mkdirSync(distDir, { recursive: true });
fs.mkdirSync(staticDir, { recursive: true });

async function run() {
  console.log('[1/6] Preparing twa-manifest.json...');
  const manifestData = {
    packageId: 'vn.babyguard.ai',
    host: 'encryption-tba-show-dig.trycloudflare.com',
    name: 'BabyGuard AI - Vệ Sĩ Bé Yêu',
    launcherName: 'BabyGuard',
    display: 'standalone',
    themeColor: '#020617',
    themeColorDark: '#020617',
    navigationColor: '#020617',
    navigationColorDark: '#020617',
    navigationDividerColor: '#1F293D',
    navigationDividerColorDark: '#1F293D',
    backgroundColor: '#020617',
    enableNotifications: true,
    startUrl: '/?source=pwa',
    iconUrl: 'http://localhost:8080/static/icons/icon-512.png',
    maskableIconUrl: 'http://localhost:8080/static/icons/icon-maskable-512.png',
    splashScreenFadeOutDuration: 300,
    signingKey: {
      path: keystorePath,
      alias: 'babyguard'
    },
    appVersionCode: 1,
    appVersion: '1.0.0',
    shortcuts: [],
    generatorApp: 'bubblewrap',
    webManifestUrl: 'http://localhost:8080/manifest.json',
    fallbackType: 'customtabs',
    features: {},
    alphaDependencies: { enabled: false },
    enableSiteSettingsShortcut: true,
    isChromeOSOnly: false,
    isMetaQuest: false,
    minSdkVersion: 24,
    orientation: 'portrait-primary',
    fingerprints: [],
    additionalTrustedOrigins: []
  };

  const twaManifest = new TwaManifest(manifestData);
  const log = new ConsoleLog('TwaBuild');
  const generator = new TwaGenerator();

  console.log('[2/6] Generating Android Project from template...');
  await generator.createTwaProject(projectDir, twaManifest, log);
  await twaManifest.saveToFile(path.join(projectDir, 'twa-manifest.json'));

  console.log('[3/6] Setting local.properties, manifest & gradle optimizations...');
  const localProps = 'sdk.dir=/Users/nvtthanh11/.bubblewrap/android_sdk\n';
  fs.writeFileSync(path.join(projectDir, 'local.properties'), localProps);

  const gradlewPath = path.join(projectDir, 'gradlew');
  fs.chmodSync(gradlewPath, '755');

  // Fix AndroidManifest.xml package attribute for AGP 8+
  const manifestPath = path.join(projectDir, 'app/src/main/AndroidManifest.xml');
  if (fs.existsSync(manifestPath)) {
    let m = fs.readFileSync(manifestPath, 'utf8');
    m = m.replace(/package="vn\.babyguard\.ai"/g, '');
    fs.writeFileSync(manifestPath, m);
  }

  // Ensure minSdkVersion 24 in app/build.gradle
  const buildGradlePath = path.join(projectDir, 'app/build.gradle');
  if (fs.existsSync(buildGradlePath)) {
    let bg = fs.readFileSync(buildGradlePath, 'utf8');
    bg = bg.replace(/minSdkVersion\s+21/g, 'minSdkVersion 24');
    fs.writeFileSync(buildGradlePath, bg);
  }

  // Ensure gradle.properties has proper jvmargs
  const gradlePropsPath = path.join(projectDir, 'gradle.properties');
  let gradleProps = fs.existsSync(gradlePropsPath) ? fs.readFileSync(gradlePropsPath, 'utf8') : '';
  if (!gradleProps.includes('org.gradle.jvmargs')) {
    gradleProps += '\norg.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8\nandroid.useAndroidX=true\n';
    fs.writeFileSync(gradlePropsPath, gradleProps);
  }

  const env = {
    ...process.env,
    JAVA_HOME: '/Users/nvtthanh11/.bubblewrap/jdk/jdk-17.0.11+9/Contents/Home',
    ANDROID_HOME: '/Users/nvtthanh11/.bubblewrap/android_sdk',
    PATH: `/Users/nvtthanh11/.bubblewrap/jdk/jdk-17.0.11+9/Contents/Home/bin:/Users/nvtthanh11/.bubblewrap/android_sdk/tools/bin:${process.env.PATH}`
  };

  console.log('[4/6] Running Gradle assembleRelease (Building APK)...');
  execSync('./gradlew assembleRelease --stacktrace', { cwd: projectDir, env, stdio: 'inherit' });

  const unsignedApk = path.join(projectDir, 'app/build/outputs/apk/release/app-release-unsigned.apk');
  const finalApk = path.join(distDir, 'BabyGuard_AI.apk');
  const apksignerPath = '/Users/nvtthanh11/.bubblewrap/android_sdk/build-tools/36.1.0/apksigner';

  console.log('[5/6] Signing APK with apksigner...');
  execSync(`"${apksignerPath}" sign --ks "${keystorePath}" --ks-key-alias babyguard --ks-pass pass:babyguard123 --key-pass pass:babyguard123 --out "${finalApk}" "${unsignedApk}"`, { env, stdio: 'inherit' });

  // Verify signed APK
  execSync(`"${apksignerPath}" verify --verbose "${finalApk}"`, { env, stdio: 'inherit' });
  console.log('✅ Signed APK verified successfully!');

  // Copy to static dir for 1-tap download
  fs.copyFileSync(finalApk, path.join(staticDir, 'BabyGuard_AI.apk'));
  console.log('✅ BabyGuard_AI.apk copied to static web folder for phone download!');

  console.log('[6/6] Running Gradle bundleRelease (Building AAB for Google Play Store)...');
  try {
    execSync('./gradlew bundleRelease --stacktrace', { cwd: projectDir, env, stdio: 'inherit' });
    const unsignedAab = path.join(projectDir, 'app/build/outputs/bundle/release/app-release.aab');
    const finalAab = path.join(distDir, 'BabyGuard_AI.aab');
    const jarsignerPath = '/Users/nvtthanh11/.bubblewrap/jdk/jdk-17.0.11+9/Contents/Home/bin/jarsigner';
    execSync(`"${jarsignerPath}" -keystore "${keystorePath}" -storepass babyguard123 -keypass babyguard123 "${unsignedAab}" babyguard`, { env, stdio: 'inherit' });
    fs.copyFileSync(unsignedAab, finalAab);
    console.log('✅ Signed AAB for Google Play Store created at:', finalAab);
  } catch (aabErr) {
    console.warn('⚠️ AAB bundle creation note:', aabErr.message);
  }

  const apkStats = fs.statSync(finalApk);
  console.log(`\n🎉 BUILD COMPLETED SUCCESSFULLY!`);
  console.log(`📦 APK File: ${finalApk} (${(apkStats.size / 1024 / 1024).toFixed(2)} MB)`);
}

run().catch(err => {
  console.error('❌ Build failed:', err);
  process.exit(1);
});
