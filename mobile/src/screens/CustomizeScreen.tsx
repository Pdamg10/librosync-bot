import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  SafeAreaView,
  Image,
  Alert,
} from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import {
  useAppTheme,
  PRESET_THEMES,
  PRESET_GRADIENTS,
  PRESET_MEDIA_WALLPAPERS,
  BackgroundType,
} from '../theme/ThemeContext';

interface CustomizeScreenProps {
  onOpenDrawer?: () => void;
  onBack?: () => void;
}

export function CustomizeScreen({ onOpenDrawer, onBack }: CustomizeScreenProps) {
  const {
    theme,
    setSolidTheme,
    setGradientTheme,
    setMediaTheme,
    setMediaOverlayOpacity,
    resetToDefault,
  } = useAppTheme();

  const [activeTab, setActiveTab] = useState<BackgroundType>(theme.backgroundType);
  const [isPickingMedia, setIsPickingMedia] = useState<boolean>(false);

  const handlePickLocalMedia = async () => {
    try {
      setIsPickingMedia(true);
      const result = await DocumentPicker.getDocumentAsync({
        type: ['image/*', 'video/*'],
        copyToCacheDirectory: true,
      });

      if (!result.canceled && result.assets && result.assets.length > 0) {
        const file = result.assets[0];
        setMediaTheme(file.uri, file.name, theme.mediaOverlayOpacity, true);
        setActiveTab('media');
        Alert.alert('¡Fondo aplicado!', `Se ha establecido "${file.name}" como fondo de la aplicación.`);
      }
    } catch (err) {
      Alert.alert('Error', 'No se pudo seleccionar el archivo multimedia.');
    } finally {
      setIsPickingMedia(false);
    }
  };

  const currentColors = theme.colors;

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: currentColors.canvasBg }]}>
      {/* Header */}
      <View style={[styles.header, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}>
        <View style={styles.headerLeft}>
          {onOpenDrawer && (
            <TouchableOpacity
              onPress={onOpenDrawer}
              style={[styles.menuBtn, { backgroundColor: currentColors.cardSecondaryBg }]}
            >
              <Text style={[styles.menuIcon, { color: currentColors.textPrimary }]}>☰</Text>
            </TouchableOpacity>
          )}
          <View>
            <Text style={[styles.headerTitle, { color: currentColors.textPrimary }]}>
              Personalización
            </Text>
            <Text style={[styles.headerSubtitle, { color: currentColors.textSecondary }]}>
              Estilo, Fondos y Temas Visuales
            </Text>
          </View>
        </View>

        {onBack && (
          <TouchableOpacity
            onPress={onBack}
            style={[styles.doneBtn, { backgroundColor: currentColors.accent }]}
          >
            <Text style={styles.doneBtnText}>Listo</Text>
          </TouchableOpacity>
        )}
      </View>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        {/* Selector de Modo: Sólido / Degradado / Multimedia */}
        <View style={[styles.modeTabs, { backgroundColor: currentColors.cardSecondaryBg }]}>
          <TouchableOpacity
            style={[styles.modeTab, activeTab === 'solid' && styles.modeTabActive]}
            onPress={() => setActiveTab('solid')}
          >
            <Text style={[styles.modeTabText, activeTab === 'solid' && styles.modeTabTextActive]}>
              🎨 Color Sólido
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.modeTab, activeTab === 'gradient' && styles.modeTabActive]}
            onPress={() => setActiveTab('gradient')}
          >
            <Text style={[styles.modeTabText, activeTab === 'gradient' && styles.modeTabTextActive]}>
              🌈 Degradado
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.modeTab, activeTab === 'media' && styles.modeTabActive]}
            onPress={() => setActiveTab('media')}
          >
            <Text style={[styles.modeTabText, activeTab === 'media' && styles.modeTabTextActive]}>
              🖼️ Foto / GIF / Video
            </Text>
          </TouchableOpacity>
        </View>

        {/* VISTA PREVIA EN TIEMPO REAL DEL LIBRO Y ESTANTE */}
        <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
          VISTA PREVIA EN VIVO
        </Text>
        <View
          style={[
            styles.previewCanvas,
            {
              backgroundColor: currentColors.cardBg,
              borderColor: currentColors.cardBorder,
            },
          ]}
        >
          {theme.backgroundType === 'media' && theme.mediaUri && (
            <Image
              source={{ uri: theme.mediaUri }}
              style={StyleSheet.absoluteFill}
              resizeMode="cover"
            />
          )}

          {/* Mini Estante y Libro 3D */}
          <View style={styles.previewBookContainer}>
            <View style={styles.previewHardcover}>
              {/* Lomo 3D */}
              <View style={styles.previewSpineHighlight} />
              <View style={styles.previewSpineShadow} />

              <View style={styles.previewCover}>
                <Text style={styles.previewBookEmblem}>✨</Text>
                <Text style={styles.previewBookTitle}>LibroSync</Text>
                <Text style={styles.previewBookAuthor}>Edición Especial</Text>
              </View>

              {/* Cinta marcapáginas dorada */}
              <View style={styles.previewRibbon} />

              {/* Bloque de páginas */}
              <View style={styles.previewPageBlock} />
            </View>

            {/* Estante de madera inferior */}
            <View style={[styles.previewShelfBar, { backgroundColor: currentColors.shelfBar }]} />
            <View style={[styles.previewShelfEdge, { backgroundColor: currentColors.shelfBarEdge }]} />

            {/* Título y autor debajo */}
            <Text style={[styles.previewUnderTitle, { color: currentColors.textPrimary }]}>
              Cien Años de Soledad
            </Text>
            <Text style={[styles.previewUnderAuthor, { color: currentColors.textSecondary }]}>
              Gabriel García Márquez
            </Text>
          </View>

          <Text style={[styles.previewCaption, { color: currentColors.textSecondary }]}>
            {theme.backgroundType === 'solid' && `Color sólido activo`}
            {theme.backgroundType === 'gradient' && `Degradado suave activo`}
            {theme.backgroundType === 'media' && `Fondo multimedia: ${theme.mediaName || 'Personalizado'}`}
          </Text>
        </View>

        {/* CONTROLES DEL MODO 1: COLOR SÓLIDO */}
        {activeTab === 'solid' && (
          <View style={styles.optionsBlock}>
            <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
              PALETAS DE COLOR SÓLIDO
            </Text>
            {Object.entries(PRESET_THEMES).map(([key, t]) => {
              const isSelected = theme.backgroundType === 'solid' && theme.solidColor === t.hex;
              return (
                <TouchableOpacity
                  key={key}
                  style={[
                    styles.optionRow,
                    { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder },
                    isSelected && { borderColor: currentColors.accent, borderWidth: 2 },
                  ]}
                  onPress={() => setSolidTheme(t.hex, t.isDark, t.colors)}
                >
                  <View
                    style={[
                      styles.colorCircle,
                      { backgroundColor: t.hex, borderColor: t.isDark ? '#3D3631' : '#DFD5C6' },
                    ]}
                  />
                  <View style={styles.optionRowTextCol}>
                    <Text style={[styles.optionRowTitle, { color: currentColors.textPrimary }]}>
                      {t.name}
                    </Text>
                    <Text style={[styles.optionRowSubtitle, { color: currentColors.textSecondary }]}>
                      {t.isDark ? 'Tema Oscuro • Alto Contraste' : 'Tema Claro • Paleta Cálida'}
                    </Text>
                  </View>
                  {isSelected && (
                    <View style={[styles.checkCircle, { backgroundColor: currentColors.accent }]}>
                      <Text style={styles.checkIcon}>✓</Text>
                    </View>
                  )}
                </TouchableOpacity>
              );
            })}
          </View>
        )}

        {/* CONTROLES DEL MODO 2: DEGRADADOS */}
        {activeTab === 'gradient' && (
          <View style={styles.optionsBlock}>
            <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
              DEGRADADOS SUAVES Y RELAJANTES
            </Text>
            {PRESET_GRADIENTS.map((g) => {
              const isSelected =
                theme.backgroundType === 'gradient' &&
                theme.gradientColors[0] === g.colors[0] &&
                theme.gradientColors[1] === g.colors[1];
              return (
                <TouchableOpacity
                  key={g.id}
                  style={[
                    styles.optionRow,
                    { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder },
                    isSelected && { borderColor: currentColors.accent, borderWidth: 2 },
                  ]}
                  onPress={() => setGradientTheme(g.colors, g.isDark)}
                >
                  <View style={styles.gradientPreviewBox}>
                    <View style={{ flex: 1, backgroundColor: g.colors[0] }} />
                    <View style={{ flex: 1, backgroundColor: g.colors[1] }} />
                  </View>
                  <View style={styles.optionRowTextCol}>
                    <Text style={[styles.optionRowTitle, { color: currentColors.textPrimary }]}>
                      {g.name}
                    </Text>
                    <Text style={[styles.optionRowSubtitle, { color: currentColors.textSecondary }]}>
                      {g.isDark ? 'Gradiente Nocturno' : 'Gradiente Suave'}
                    </Text>
                  </View>
                  {isSelected && (
                    <View style={[styles.checkCircle, { backgroundColor: currentColors.accent }]}>
                      <Text style={styles.checkIcon}>✓</Text>
                    </View>
                  )}
                </TouchableOpacity>
              );
            })}
          </View>
        )}

        {/* CONTROLES DEL MODO 3: MULTIMEDIA (FOTO / GIF / VIDEO) */}
        {activeTab === 'media' && (
          <View style={styles.optionsBlock}>
            {/* Botón para subir desde la galería del teléfono */}
            <TouchableOpacity
              style={[styles.uploadMediaCard, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}
              onPress={handlePickLocalMedia}
              disabled={isPickingMedia}
            >
              <Text style={styles.uploadMediaIcon}>📂</Text>
              <Text style={[styles.uploadMediaTitle, { color: currentColors.textPrimary }]}>
                {isPickingMedia ? 'Cargando archivo...' : 'Elegir Foto o GIF de tu Teléfono'}
              </Text>
              <Text style={[styles.uploadMediaSubtitle, { color: currentColors.textSecondary }]}>
                Selecciona cualquier imagen, fondo animado o captura de tu galería
              </Text>
            </TouchableOpacity>

            {/* Selector de Opacidad del Velo Protector */}
            <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
              INTENSIDAD DEL VELO PROTECTOR DE LECTURA
            </Text>
            <View style={[styles.opacityRow, { backgroundColor: currentColors.cardSecondaryBg }]}>
              {[
                { label: 'Suave (30%)', value: 0.3 },
                { label: 'Medio (50%)', value: 0.5 },
                { label: 'Oscuro (70%)', value: 0.7 },
                { label: 'Noche (85%)', value: 0.85 },
              ].map((op) => (
                <TouchableOpacity
                  key={op.label}
                  style={[
                    styles.opacityBtn,
                    theme.mediaOverlayOpacity === op.value && styles.opacityBtnActive,
                  ]}
                  onPress={() => setMediaOverlayOpacity(op.value)}
                >
                  <Text
                    style={[
                      styles.opacityBtnText,
                      theme.mediaOverlayOpacity === op.value && styles.opacityBtnTextActive,
                    ]}
                  >
                    {op.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Fondos Predefinidos de Calidad */}
            <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
              FONDOS DE BIBLIOTECA PREDEFINIDOS
            </Text>
            <View style={styles.wallpapersGrid}>
              {PRESET_MEDIA_WALLPAPERS.map((w) => {
                const isSelected = theme.backgroundType === 'media' && theme.mediaUri === w.uri;
                return (
                  <TouchableOpacity
                    key={w.id}
                    style={[
                      styles.wallpaperItem,
                      isSelected && { borderColor: currentColors.accent, borderWidth: 3 },
                    ]}
                    onPress={() => setMediaTheme(w.uri, w.name, theme.mediaOverlayOpacity, w.isDark)}
                  >
                    <Image source={{ uri: w.uri }} style={styles.wallpaperThumb} />
                    <View style={styles.wallpaperOverlay}>
                      <Text style={styles.wallpaperName} numberOfLines={1}>
                        {w.name}
                      </Text>
                    </View>
                    {isSelected && (
                      <View style={[styles.wallpaperBadge, { backgroundColor: currentColors.accent }]}>
                        <Text style={styles.wallpaperBadgeText}>Activo</Text>
                      </View>
                    )}
                  </TouchableOpacity>
                );
              })}
            </View>
          </View>
        )}

        {/* Botón Restablecer */}
        <TouchableOpacity
          style={[styles.resetBtn, { borderColor: currentColors.cardBorder }]}
          onPress={() => {
            resetToDefault();
            setActiveTab('solid');
            Alert.alert('Tema restablecido', 'Se ha vuelto a la paleta crema original.');
          }}
        >
          <Text style={[styles.resetBtnText, { color: currentColors.textSecondary }]}>
            ↺ Restablecer a Paleta Crema Original
          </Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 18,
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
  doneBtn: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 10,
  },
  doneBtnText: {
    color: '#FAF7F2',
    fontWeight: '700',
    fontSize: 13,
  },
  scroll: {
    flex: 1,
  },
  content: {
    padding: 16,
    paddingBottom: 40,
  },
  modeTabs: {
    flexDirection: 'row',
    borderRadius: 12,
    padding: 4,
    marginBottom: 18,
  },
  modeTab: {
    flex: 1,
    paddingVertical: 8,
    alignItems: 'center',
    borderRadius: 8,
  },
  modeTabActive: {
    backgroundColor: '#2C2523',
  },
  modeTabText: {
    fontSize: 11,
    fontWeight: '600',
    color: '#7A6E65',
  },
  modeTabTextActive: {
    color: '#FAF7F2',
    fontWeight: '700',
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.8,
    marginBottom: 10,
    marginTop: 10,
    textTransform: 'uppercase',
  },
  previewCanvas: {
    height: 250,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 18,
    position: 'relative',
    overflow: 'hidden',
    padding: 16,
  },
  previewBookContainer: {
    alignItems: 'center',
    zIndex: 2,
  },
  previewHardcover: {
    width: 105,
    height: 145,
    backgroundColor: '#3B5B75',
    borderTopRightRadius: 14,
    borderBottomRightRadius: 14,
    position: 'relative',
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 3, height: 6 },
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 6,
  },
  previewSpineHighlight: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 7,
    backgroundColor: 'rgba(255, 255, 255, 0.28)',
  },
  previewSpineShadow: {
    position: 'absolute',
    left: 7,
    top: 0,
    bottom: 0,
    width: 3,
    backgroundColor: 'rgba(0, 0, 0, 0.25)',
  },
  previewCover: {
    alignItems: 'center',
    paddingHorizontal: 8,
  },
  previewBookEmblem: {
    fontSize: 22,
    marginBottom: 4,
  },
  previewBookTitle: {
    fontSize: 12,
    fontWeight: '800',
    color: '#FFFFFF',
    textAlign: 'center',
  },
  previewBookAuthor: {
    fontSize: 9,
    color: 'rgba(255, 255, 255, 0.8)',
    marginTop: 2,
  },
  previewRibbon: {
    position: 'absolute',
    right: 18,
    bottom: -10,
    width: 12,
    height: 18,
    backgroundColor: '#EAA023',
    borderRadius: 2,
  },
  previewPageBlock: {
    position: 'absolute',
    bottom: 0,
    left: 8,
    right: 0,
    height: 4,
    backgroundColor: '#FAF7EE',
  },
  previewShelfBar: {
    width: 150,
    height: 7,
    marginTop: 10,
    borderRadius: 2,
  },
  previewShelfEdge: {
    width: 150,
    height: 3,
    borderBottomLeftRadius: 2,
    borderBottomRightRadius: 2,
  },
  previewUnderTitle: {
    fontSize: 12,
    fontWeight: '700',
    marginTop: 6,
  },
  previewUnderAuthor: {
    fontSize: 10,
    marginTop: 1,
  },
  previewCaption: {
    fontSize: 11,
    marginTop: 8,
    zIndex: 2,
    fontWeight: '600',
  },
  optionsBlock: {
    gap: 8,
  },
  optionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    marginBottom: 4,
  },
  colorCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 2,
    marginRight: 12,
  },
  gradientPreviewBox: {
    width: 48,
    height: 30,
    borderRadius: 8,
    flexDirection: 'row',
    overflow: 'hidden',
    marginRight: 12,
  },
  optionRowTextCol: {
    flex: 1,
  },
  optionRowTitle: {
    fontSize: 14,
    fontWeight: '700',
  },
  optionRowSubtitle: {
    fontSize: 11,
    marginTop: 2,
  },
  checkCircle: {
    width: 24,
    height: 24,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkIcon: {
    fontSize: 13,
    fontWeight: '900',
    color: '#FAF7F2',
  },
  uploadMediaCard: {
    padding: 16,
    borderRadius: 14,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 10,
  },
  uploadMediaIcon: {
    fontSize: 34,
    marginBottom: 6,
  },
  uploadMediaTitle: {
    fontSize: 14,
    fontWeight: '700',
    marginBottom: 2,
  },
  uploadMediaSubtitle: {
    fontSize: 11,
    textAlign: 'center',
  },
  opacityRow: {
    flexDirection: 'row',
    borderRadius: 12,
    padding: 4,
    marginBottom: 14,
  },
  opacityBtn: {
    flex: 1,
    paddingVertical: 8,
    alignItems: 'center',
    borderRadius: 8,
  },
  opacityBtnActive: {
    backgroundColor: '#2C2523',
  },
  opacityBtnText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#7A6E65',
  },
  opacityBtnTextActive: {
    color: '#FAF7F2',
    fontWeight: '700',
  },
  wallpapersGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    marginBottom: 16,
  },
  wallpaperItem: {
    width: '48%',
    height: 110,
    borderRadius: 12,
    overflow: 'hidden',
    position: 'relative',
    borderWidth: 1,
    borderColor: '#DFD5C6',
  },
  wallpaperThumb: {
    width: '100%',
    height: '100%',
  },
  wallpaperOverlay: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.55)',
    paddingVertical: 5,
    paddingHorizontal: 8,
  },
  wallpaperName: {
    fontSize: 10,
    color: '#FFFFFF',
    fontWeight: '700',
  },
  wallpaperBadge: {
    position: 'absolute',
    top: 6,
    right: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
  },
  wallpaperBadgeText: {
    fontSize: 9,
    color: '#FAF7F2',
    fontWeight: '800',
  },
  resetBtn: {
    marginTop: 18,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1,
    alignItems: 'center',
  },
  resetBtnText: {
    fontSize: 13,
    fontWeight: '600',
  },
});
