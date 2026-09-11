import React, { useState, useEffect } from 'react';
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
import {
  getApiBaseUrl,
  setApiBaseUrl,
  checkServerHealth,
  autoDiscoverServer,
  DEFAULT_HOST_URL,
} from '../services/api';
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
  const [isConnected, setIsConnected] = useState<boolean | null>(null);
  const [pingMs, setPingMs] = useState<number | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Probar conectividad al montar la pantalla
  useEffect(() => {
    handleTestConnection();
  }, []);

  const handleTestConnection = async () => {
    setTesting(true);
    const startTime = Date.now();
    try {
      const isHealthy = await checkServerHealth();
      const elapsed = Date.now() - startTime;
      setIsConnected(isHealthy);
      setPingMs(isHealthy ? elapsed : null);
    } catch {
      setIsConnected(false);
      setPingMs(null);
    } finally {
      setTesting(false);
    }
  };

  const handleAutoReconnect = async () => {
    setTesting(true);
    try {
      const discovered = await autoDiscoverServer();
      if (discovered) {
        setServerUrlText(discovered);
        setIsConnected(true);
        Alert.alert('¡Conexión Exitosa!', `Conectado a la biblioteca en:\n${discovered}`);
      } else {
        setIsConnected(false);
        Alert.alert(
          'Servidor no encontrado',
          'Asegúrate de que tu teléfono y tu computadora estén conectados a la misma red Wi-Fi y el servidor esté iniciado.'
        );
      }
    } finally {
      setTesting(false);
    }
  };

  const handleSaveUrl = () => {
    const trimmed = serverUrl.trim();
    if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://')) {
      Alert.alert('Dirección Inválida', 'La dirección debe comenzar con http:// o https://');
      return;
    }
    setApiBaseUrl(trimmed);
    Alert.alert('Guardado', `Dirección configurada a:\n${trimmed}`);
    handleTestConnection();
  };

  const setPreset = (presetUrl: string) => {
    setServerUrlText(presetUrl);
    setApiBaseUrl(presetUrl);
    setTimeout(handleTestConnection, 100);
  };

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: 'transparent' }]}>
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
              Estado del Servidor y Red
            </Text>
          </View>
        </View>
      </View>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        {/* TARJETA EXPLICATIVA AMIGABLE (Para responder duda del usuario) */}
        <View style={[styles.explanationCard, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.explanationTitle, { color: c.textPrimary }]}>
            💡 ¿Para qué sirve esta opción?
          </Text>
          <Text style={[styles.explanationText, { color: c.textSecondary }]}>
            Esta pantalla le permite a tu teléfono conectarse con la biblioteca central donde están guardados tus libros, sagas y lecturas del club.
            {'\n\n'}
            Si tu teléfono y tu computadora están en la misma red Wi-Fi, la conexión funciona automáticamente. Solo necesitas esta pantalla si cambias de red Wi-Fi o deseas verificar que la app esté en línea.
          </Text>
        </View>

        {/* TARJETA DE ESTADO DE CONEXIÓN */}
        <View style={[styles.card, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.cardTitle, { color: c.textPrimary }]}>
            📡 Estado de Conexión
          </Text>

          <View style={styles.statusRow}>
            <View
              style={[
                styles.statusPill,
                isConnected === true
                  ? styles.statusPillConnected
                  : isConnected === false
                  ? styles.statusPillDisconnected
                  : styles.statusPillTesting,
              ]}
            >
              <Text style={styles.statusDot}>
                {isConnected === true ? '🟢' : isConnected === false ? '🔴' : '🟡'}
              </Text>
              <Text
                style={[
                  styles.statusPillLabel,
                  isConnected === true
                    ? styles.statusLabelConnected
                    : isConnected === false
                    ? styles.statusLabelDisconnected
                    : styles.statusLabelTesting,
                ]}
              >
                {isConnected === true
                  ? 'Conectado a la Biblioteca'
                  : isConnected === false
                  ? 'Sin Conexión con Servidor'
                  : 'Comprobando conexión...'}
              </Text>
            </View>

            {pingMs !== null && (
              <Text style={[styles.pingText, { color: c.textMuted }]}>{pingMs} ms</Text>
            )}
          </View>

          <TouchableOpacity
            style={[styles.reconnectBtn, { backgroundColor: c.accent }]}
            onPress={handleAutoReconnect}
            disabled={testing}
          >
            {testing ? (
              <ActivityIndicator color="#FFFFFF" size="small" />
            ) : (
              <Text style={styles.reconnectBtnText}>🔄 Reconectar Automáticamente</Text>
            )}
          </TouchableOpacity>
        </View>

        {/* BOTÓN DESPLEGABLE: AJUSTES AVANZADOS DE RED */}
        <TouchableOpacity
          style={[styles.advancedToggleRow, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
          onPress={() => setShowAdvanced(!showAdvanced)}
        >
          <View style={styles.advancedToggleLeft}>
            <Text style={{ fontSize: 18 }}>⚙️</Text>
            <Text style={[styles.advancedToggleTitle, { color: c.textPrimary }]}>
              Ajustes Avanzados de Red
            </Text>
          </View>
          <Text style={[styles.advancedChevron, { color: c.textMuted }]}>
            {showAdvanced ? '▲ Ocultar' : '▼ Mostrar'}
          </Text>
        </TouchableOpacity>

        {showAdvanced && (
          <View style={[styles.advancedBlock, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
            <Text style={[styles.advancedHelp, { color: c.textSecondary }]}>
              Dirección de red del servidor (IP y puerto). Modifícala únicamente si tu router asignó una dirección diferente:
            </Text>

            <TextInput
              style={[styles.input, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder, color: c.textPrimary }]}
              value={serverUrl}
              onChangeText={setServerUrlText}
              placeholder="http://10.46.1.120:8000"
              placeholderTextColor={c.textMuted}
              autoCapitalize="none"
              autoCorrect={false}
            />

            {/* Accesos rápidos de red */}
            <View style={styles.presetsRow}>
              <TouchableOpacity
                onPress={() => setPreset(DEFAULT_HOST_URL)}
                style={[styles.presetBtn, { backgroundColor: c.cardSecondaryBg }]}
              >
                <Text style={[styles.presetBtnText, { color: c.textPrimary }]}>Wi-Fi Host (10.46.1.120)</Text>
              </TouchableOpacity>

              <TouchableOpacity
                onPress={() => setPreset('http://10.0.2.2:8000')}
                style={[styles.presetBtn, { backgroundColor: c.cardSecondaryBg }]}
              >
                <Text style={[styles.presetBtnText, { color: c.textSecondary }]}>Emulador</Text>
              </TouchableOpacity>
            </View>

            <TouchableOpacity onPress={handleSaveUrl} style={[styles.saveBtn, { backgroundColor: c.accent }]}>
              <Text style={styles.saveBtnText}>💾 Guardar Dirección</Text>
            </TouchableOpacity>

            {/* Diagnóstico técnico */}
            <View style={[styles.diagBox, { borderTopColor: c.cardBorder }]}>
              <Text style={[styles.diagTitle, { color: c.textMuted }]}>DIAGNÓSTICO DEL DISPOSITIVO</Text>
              <Text style={[styles.diagLine, { color: c.textSecondary }]}>
                • Tipo de pantalla: {isTablet ? 'Tablet / Pantalla grande' : 'Teléfono móvil'}
              </Text>
              <Text style={[styles.diagLine, { color: c.textSecondary }]}>
                • Resolución: {Math.round(width)} x {Math.round(height)} px
              </Text>
              <Text style={[styles.diagLine, { color: c.textSecondary }]}>
                • Columnas adaptativas: {numColumns}
              </Text>
            </View>
          </View>
        )}

        {/* Acerca de la App */}
        <View style={[styles.card, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.cardTitle, { color: c.textPrimary }]}>ℹ️ Acerca de Anaquel • LibroSync</Text>
          <Text style={[styles.aboutText, { color: c.textSecondary }]}>
            Versión: 1.1.0 • Club de Lectura{'\n'}
            Sincronización en tiempo real con Telegram y Asistente Griffin IA impulsado por Google Gemini.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderBottomWidth: 1,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  menuBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuIcon: {
    fontSize: 18,
    fontWeight: '700',
  },
  headerTitle: {
    fontSize: 17,
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
  explanationCard: {
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    marginBottom: 16,
  },
  explanationTitle: {
    fontSize: 14,
    fontWeight: '700',
    marginBottom: 6,
  },
  explanationText: {
    fontSize: 12,
    lineHeight: 18,
  },
  card: {
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    marginBottom: 16,
  },
  cardTitle: {
    fontSize: 14,
    fontWeight: '700',
    marginBottom: 12,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 14,
  },
  statusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
  },
  statusPillConnected: {
    backgroundColor: '#D1FAE5',
  },
  statusPillDisconnected: {
    backgroundColor: '#FEE2E2',
  },
  statusPillTesting: {
    backgroundColor: '#FEF3C7',
  },
  statusDot: {
    fontSize: 12,
    marginRight: 6,
  },
  statusPillLabel: {
    fontSize: 12,
    fontWeight: '700',
  },
  statusLabelConnected: {
    color: '#047857',
  },
  statusLabelDisconnected: {
    color: '#DC2626',
  },
  statusLabelTesting: {
    color: '#B45309',
  },
  pingText: {
    fontSize: 11,
    fontWeight: '600',
  },
  reconnectBtn: {
    paddingVertical: 11,
    borderRadius: 10,
    alignItems: 'center',
  },
  reconnectBtnText: {
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '700',
  },
  advancedToggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    marginBottom: 12,
  },
  advancedToggleLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  advancedToggleTitle: {
    fontSize: 13,
    fontWeight: '700',
  },
  advancedChevron: {
    fontSize: 11,
    fontWeight: '700',
  },
  advancedBlock: {
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    marginBottom: 16,
  },
  advancedHelp: {
    fontSize: 11,
    lineHeight: 16,
    marginBottom: 10,
  },
  input: {
    height: 42,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    fontSize: 13,
    marginBottom: 10,
  },
  presetsRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
  },
  presetBtn: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
  },
  presetBtnText: {
    fontSize: 11,
    fontWeight: '600',
  },
  saveBtn: {
    paddingVertical: 10,
    borderRadius: 10,
    alignItems: 'center',
    marginBottom: 14,
  },
  saveBtnText: {
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '700',
  },
  diagBox: {
    borderTopWidth: 1,
    paddingTop: 12,
  },
  diagTitle: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.8,
    marginBottom: 6,
  },
  diagLine: {
    fontSize: 11,
    lineHeight: 18,
  },
  aboutText: {
    fontSize: 12,
    lineHeight: 18,
  },
});
