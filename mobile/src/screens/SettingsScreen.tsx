import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Alert,
  ActivityIndicator,
  SafeAreaView,
} from 'react-native';
import { getApiBaseUrl, setApiBaseUrl, checkServerHealth } from '../services/api';
import { useResponsive } from '../hooks/useResponsive';
import { useAppTheme } from '../theme/ThemeContext';

interface SettingsScreenProps {
  onOpenDrawer?: () => void;
}

export const SettingsScreen: React.FC<SettingsScreenProps> = ({ onOpenDrawer }) => {
  const { theme } = useAppTheme();
  const c = theme.colors;
  const { isTablet, width, height, numColumns } = useResponsive();

  const [serverUrl, setServerUrlText] = useState(getApiBaseUrl());
  const [testing, setTesting] = useState(false);
  const [serverStatus, setServerStatus] = useState<string | null>(null);

  const handleSaveUrl = () => {
    const trimmed = serverUrl.trim();
    if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://')) {
      Alert.alert('URL Inválida', 'La URL debe comenzar con http:// o https://');
      return;
    }
    setApiBaseUrl(trimmed);
    Alert.alert('Guardado', `Servidor configurado a:\n${trimmed}`);
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setServerStatus(null);
    const startTime = Date.now();
    try {
      const isHealthy = await checkServerHealth();
      const elapsed = Date.now() - startTime;
      if (isHealthy) {
        setServerStatus(`✅ Conectado exitosamente (${elapsed}ms)`);
      } else {
        setServerStatus('❌ El servidor respondió con error.');
      }
    } catch (e: any) {
      setServerStatus('❌ No se pudo conectar al servidor.');
    } finally {
      setTesting(false);
    }
  };

  const setPreset = (presetUrl: string) => {
    setServerUrlText(presetUrl);
    setApiBaseUrl(presetUrl);
    setServerStatus(null);
  };

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: c.canvasBg }]}>
      {/* Header */}
      <View style={[styles.header, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
        <View style={styles.headerLeft}>
          {onOpenDrawer && (
            <TouchableOpacity
              onPress={onOpenDrawer}
              style={[styles.menuBtn, { backgroundColor: c.cardSecondaryBg }]}
            >
              <Text style={[styles.menuIcon, { color: c.textPrimary }]}>☰</Text>
            </TouchableOpacity>
          )}
          <View>
            <Text style={[styles.headerTitle, { color: c.textPrimary }]}>
              Ajustes y Conexión
            </Text>
            <Text style={[styles.headerSubtitle, { color: c.textSecondary }]}>
              Configuración de Red y Servidor
            </Text>
          </View>
        </View>
      </View>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <Text style={[styles.title, { color: c.textPrimary }]}>⚙️ Conexión con el Servidor</Text>
        <Text style={[styles.subtitle, { color: c.textSecondary }]}>
          Configura la dirección IP o URL de tu servidor backend para sincronizar tus libros con tablets o teléfonos físicos.
        </Text>

        {/* Server URL Card */}
        <View style={[styles.card, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.cardTitle, { color: c.textPrimary }]}>🌐 Dirección del Servidor Backend</Text>
          <TextInput
            style={[styles.input, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder, color: c.textPrimary }]}
            value={serverUrl}
            onChangeText={setServerUrlText}
            placeholder="http://192.168.1.XX:8000"
            placeholderTextColor={c.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
          />

          {/* Quick Presets */}
          <View style={styles.presetsRow}>
            <TouchableOpacity
              onPress={() => setPreset('http://10.0.2.2:8000')}
              style={[styles.presetBtn, { backgroundColor: c.cardSecondaryBg }]}
            >
              <Text style={[styles.presetBtnText, { color: c.textSecondary }]}>Emulador Android</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => setPreset('http://localhost:8000')}
              style={[styles.presetBtn, { backgroundColor: c.cardSecondaryBg }]}
            >
              <Text style={[styles.presetBtnText, { color: c.textSecondary }]}>Localhost</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.actionsRow}>
            <TouchableOpacity onPress={handleSaveUrl} style={[styles.saveBtn, { backgroundColor: c.accent }]}>
              <Text style={styles.saveBtnText}>💾 Guardar URL</Text>
            </TouchableOpacity>

            <TouchableOpacity
              onPress={handleTestConnection}
              disabled={testing}
              style={[styles.testBtn, { backgroundColor: c.cardSecondaryBg }]}
            >
              {testing ? (
                <ActivityIndicator color={c.textPrimary} />
              ) : (
                <Text style={[styles.testBtnText, { color: c.textPrimary }]}>📡 Probar</Text>
              )}
            </TouchableOpacity>
          </View>

          {serverStatus && (
            <View style={[styles.statusBox, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
              <Text style={[styles.statusText, { color: c.textPrimary }]}>{serverStatus}</Text>
            </View>
          )}
        </View>

        {/* Device & Layout Diagnostic Card */}
        <View style={[styles.card, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.cardTitle, { color: c.textPrimary }]}>📱 Diagnóstico de Pantalla</Text>
          <View style={styles.diagRow}>
            <Text style={[styles.diagLabel, { color: c.textSecondary }]}>Dispositivo:</Text>
            <Text style={[styles.diagValue, { color: c.textPrimary }]}>
              {isTablet ? 'Tablet / Pantalla Grande 🖥️' : 'Teléfono Móvil 📱'}
            </Text>
          </View>
          <View style={styles.diagRow}>
            <Text style={[styles.diagLabel, { color: c.textSecondary }]}>Resolución:</Text>
            <Text style={[styles.diagValue, { color: c.textPrimary }]}>{Math.round(width)} x {Math.round(height)} px</Text>
          </View>
          <View style={styles.diagRow}>
            <Text style={[styles.diagLabel, { color: c.textSecondary }]}>Columnas en Catálogo:</Text>
            <Text style={[styles.diagValue, { color: c.textPrimary }]}>{numColumns} columnas adaptativas</Text>
          </View>
        </View>

        {/* About App */}
        <View style={[styles.card, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.cardTitle, { color: c.textPrimary }]}>ℹ️ Acerca de Anaquel</Text>
          <Text style={[styles.aboutText, { color: c.textSecondary }]}>
            Versión: 1.0.0{'\n'}
            Cada libro en su estante, dentro de Telegram.{'\n'}
            Organizador inteligente de lectura con Inteligencia Artificial para teléfonos y tablets.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f172a',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  menuBtn: {
    width: 38,
    height: 38,
    borderRadius: 19,
    justifyContent: 'center',
    alignItems: 'center',
  },
  menuIcon: {
    fontSize: 20,
    fontWeight: '700',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '700',
  },
  headerSubtitle: {
    fontSize: 12,
  },
  scroll: {
    flex: 1,
  },
  content: {
    padding: 16,
    paddingBottom: 40,
  },
  title: {
    fontSize: 22,
    fontWeight: '800',
    color: '#f8fafc',
    marginBottom: 6,
  },
  subtitle: {
    fontSize: 14,
    color: '#94a3b8',
    lineHeight: 20,
    marginBottom: 20,
  },
  card: {
    backgroundColor: '#1e293b',
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: '#334155',
    marginBottom: 18,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#f8fafc',
    marginBottom: 12,
  },
  input: {
    backgroundColor: '#0f172a',
    borderWidth: 1,
    borderColor: '#334155',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: '#f8fafc',
    fontSize: 15,
    marginBottom: 10,
  },
  presetsRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
  },
  presetBtn: {
    backgroundColor: '#334155',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
  },
  presetBtnText: {
    color: '#cbd5e1',
    fontSize: 12,
    fontWeight: '600',
  },
  actionsRow: {
    flexDirection: 'row',
    gap: 10,
  },
  saveBtn: {
    flex: 1,
    backgroundColor: '#6366f1',
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
  },
  saveBtnText: {
    color: '#ffffff',
    fontSize: 14,
    fontWeight: '700',
  },
  testBtn: {
    flex: 1,
    backgroundColor: '#334155',
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
  },
  testBtnText: {
    color: '#f8fafc',
    fontSize: 14,
    fontWeight: '700',
  },
  statusBox: {
    marginTop: 12,
    padding: 10,
    backgroundColor: '#0f172a',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#334155',
  },
  statusText: {
    color: '#cbd5e1',
    fontSize: 13,
    fontWeight: '600',
  },
  diagRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
  },
  diagLabel: {
    color: '#94a3b8',
    fontSize: 13,
  },
  diagValue: {
    color: '#f8fafc',
    fontSize: 13,
    fontWeight: '600',
  },
  aboutText: {
    color: '#94a3b8',
    fontSize: 13,
    lineHeight: 20,
  },
});
