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
  TextInput,
} from 'react-native';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';
import * as DocumentPicker from 'expo-document-picker';
import {
  useAppTheme,
  PRESET_THEMES,
  PRESET_GRADIENTS,
  PRESET_WALLPAPERS,
  COLOR_PALETTE_SWATCHES,
  BackgroundType,
  isColorDark,
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
    addGradientColor,
    removeGradientColor,
    updateGradientColor,
    setMediaTheme,
    setMediaOverlayOpacity,
    toggleContrastMode,
    resetToDefault,
  } = useAppTheme();

  const [activeTab, setActiveTab] = useState<BackgroundType>(theme.backgroundType);
  const [isPickingMedia, setIsPickingMedia] = useState<boolean>(false);

  // Hex libre para color sólido
  const [customSolidHex, setCustomSolidHex] = useState<string>('#');
  // Edición de color de stop en degradado
  const [selectedGradientStopIndex, setSelectedGradientStopIndex] = useState<number | null>(null);

  const handlePickLocalMedia = async (mediaKind: 'image' | 'gif' | 'video') => {
    try {
      setIsPickingMedia(true);
      const mimeTypes =
        mediaKind === 'video'
          ? ['video/*']
          : mediaKind === 'gif'
          ? ['image/gif']
          : ['image/*'];

      const result = await DocumentPicker.getDocumentAsync({
        type: mimeTypes,
        copyToCacheDirectory: true,
      });

      if (!result.canceled && result.assets && result.assets.length > 0) {
        const file = result.assets[0];
        setMediaTheme(file.uri, mediaKind, file.name, theme.mediaOverlayOpacity, true);
        setActiveTab(mediaKind);
        Alert.alert(
          '¡Fondo personalizado aplicado!',
          `Se ha establecido "${file.name}" como fondo de la aplicación. Puedes ajustar el contraste o velo protector abajo.`
        );
      }
    } catch (err) {
      Alert.alert('Error', 'No se pudo seleccionar el archivo multimedia.');
    } finally {
      setIsPickingMedia(false);
    }
  };

  const handleApplyCustomSolidHex = () => {
    let clean = customSolidHex.trim();
    if (!clean.startsWith('#')) clean = `#${clean}`;
    if (!/^#[0-9A-Fa-f]{6}$/.test(clean)) {
      Alert.alert('Formato inválido', 'Por favor ingresa un color Hexadecimal válido (ej: #2A4365 o #F59E0B).');
      return;
    }
    setSolidTheme(clean);
    Alert.alert('Color aplicado', `Fondo sólido actualizado a ${clean}`);
  };

  const currentColors = theme.colors;

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: 'transparent' }]}>
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
              Temas, Fondos y Contraste
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
        {/* Selector de Pestañas: Sólido / Degradado / Imagen / GIF / Video */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.modeTabsScroll}>
          <View style={[styles.modeTabs, { backgroundColor: currentColors.cardSecondaryBg }]}>
            <TouchableOpacity
              style={[styles.modeTab, activeTab === 'solid' && [styles.modeTabActive, { backgroundColor: currentColors.accent }]]}
              onPress={() => setActiveTab('solid')}
            >
              <Text style={[styles.modeTabText, { color: activeTab === 'solid' ? '#FFFFFF' : currentColors.textSecondary }]}>
                🎨 Sólido
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.modeTab, activeTab === 'gradient' && [styles.modeTabActive, { backgroundColor: currentColors.accent }]]}
              onPress={() => setActiveTab('gradient')}
            >
              <Text style={[styles.modeTabText, { color: activeTab === 'gradient' ? '#FFFFFF' : currentColors.textSecondary }]}>
                🌈 Degradado
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.modeTab, activeTab === 'image' && [styles.modeTabActive, { backgroundColor: currentColors.accent }]]}
              onPress={() => setActiveTab('image')}
            >
              <Text style={[styles.modeTabText, { color: activeTab === 'image' ? '#FFFFFF' : currentColors.textSecondary }]}>
                🖼️ Imagen
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.modeTab, activeTab === 'gif' && [styles.modeTabActive, { backgroundColor: currentColors.accent }]]}
              onPress={() => setActiveTab('gif')}
            >
              <Text style={[styles.modeTabText, { color: activeTab === 'gif' ? '#FFFFFF' : currentColors.textSecondary }]}>
                🎬 GIF
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.modeTab, activeTab === 'video' && [styles.modeTabActive, { backgroundColor: currentColors.accent }]]}
              onPress={() => setActiveTab('video')}
            >
              <Text style={[styles.modeTabText, { color: activeTab === 'video' ? '#FFFFFF' : currentColors.textSecondary }]}>
                🎥 Video
              </Text>
            </TouchableOpacity>
          </View>
        </ScrollView>

        {/* TARJETA DE CONTROL DE CONTRASTE Y LEGIBILIDAD (PUNTO CRÍTICO) */}
        <View style={[styles.contrastCard, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}>
          <View style={styles.contrastTextCol}>
            <Text style={[styles.contrastCardTitle, { color: currentColors.textPrimary }]}>
              Modo de Letras & Botones
            </Text>
            <Text style={[styles.contrastCardSubtitle, { color: currentColors.textSecondary }]}>
              {theme.isDark
                ? '⚪ Contraste Claro: Texto en blanco/marfil para fondos oscuros o fotos nocturnas.'
                : '⚫ Contraste Oscuro: Texto en tinta negra/café para fondos claros o cremas.'}
            </Text>
          </View>
          <TouchableOpacity
            style={[styles.contrastToggleBtn, { backgroundColor: currentColors.cardSecondaryBg, borderColor: currentColors.cardBorder }]}
            onPress={toggleContrastMode}
          >
            <Text style={[styles.contrastToggleBtnText, { color: currentColors.textPrimary }]}>
              {theme.isDark ? '☀️ Pasar a Oscuro' : '🌙 Pasar a Claro'}
            </Text>
          </TouchableOpacity>
        </View>

        {/* VISTA PREVIA EN VIVO */}
        <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
          VISTA PREVIA EN VIVO
        </Text>
        <View
          style={[
            styles.previewCanvas,
            {
              backgroundColor: currentColors.cardBg,
              borderColor: currentColors.cardBorder,
              overflow: 'hidden',
            },
          ]}
        >
          {/* Fondo sólido en preview */}
          {theme.backgroundType === 'solid' && (
            <View
              style={[
                StyleSheet.absoluteFill,
                { backgroundColor: theme.solidColor },
              ]}
            />
          )}

          {/* Fondo degradado SVG dinámico en preview */}
          {theme.backgroundType === 'gradient' && (() => {
            const previewGradKey = theme.gradientColors.map((s) => s.replace('#', '')).join('_');
            const previewGradId = `prevGrad_${previewGradKey}`;
            const numStops = theme.gradientColors.length;
            return (
              <Svg key={`prev_svg_${previewGradKey}`} style={StyleSheet.absoluteFill} width="100%" height="100%">
                <Defs>
                  <LinearGradient id={previewGradId} x1="0%" y1="0%" x2="0%" y2="100%">
                    {theme.gradientColors.map((col, idx) => {
                      const pct = Math.round((idx / Math.max(1, numStops - 1)) * 100);
                      return (
                        <Stop
                          key={`prev_stop_${idx}_${col}`}
                          offset={`${pct}%`}
                          stopColor={col}
                          stopOpacity="1"
                        />
                      );
                    })}
                  </LinearGradient>
                </Defs>
                <Rect x="0" y="0" width="100%" height="100%" fill={`url(#${previewGradId})`} />
              </Svg>
            );
          })()}

          {theme.mediaUri && (theme.backgroundType === 'image' || theme.backgroundType === 'gif') && (
            <Image
              source={{ uri: theme.mediaUri }}
              style={StyleSheet.absoluteFill}
              resizeMode="cover"
            />
          )}

          {/* Velo protector en preview */}
          {theme.mediaUri && (
            <View
              style={[
                StyleSheet.absoluteFill,
                {
                  backgroundColor: theme.isDark ? '#000000' : '#FAF7F2',
                  opacity: theme.mediaOverlayOpacity,
                },
              ]}
            />
          )}

          {/* Mini Estante y Libro 3D */}
          <View style={styles.previewBookContainer}>
            <View style={styles.previewHardcover}>
              <View style={styles.previewSpineHighlight} />
              <View style={styles.previewSpineShadow} />

              <View style={styles.previewCover}>
                <Text style={styles.previewBookEmblem}>✨</Text>
                <Text style={styles.previewBookTitle}>LibroSync</Text>
                <Text style={styles.previewBookAuthor}>Edición Especial</Text>
              </View>

              <View style={styles.previewRibbon} />
              <View style={styles.previewPageBlock} />
            </View>

            {/* Estante de madera inferior */}
            <View style={[styles.previewShelfBar, { backgroundColor: currentColors.shelfBar }]} />
            <View style={[styles.previewShelfEdge, { backgroundColor: currentColors.shelfBarEdge }]} />

            {/* Título y autor con colores adaptados */}
            <View style={[styles.previewLabelBadge, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}>
              <Text style={[styles.previewUnderTitle, { color: currentColors.textPrimary }]}>
                Cien Años de Soledad
              </Text>
              <Text style={[styles.previewUnderAuthor, { color: currentColors.textSecondary }]}>
                Gabriel García Márquez
              </Text>
            </View>
          </View>

          <Text style={[styles.previewCaption, { color: currentColors.textSecondary }]}>
            {theme.backgroundType === 'solid' && `Fondo sólido: ${theme.solidColor}`}
            {theme.backgroundType === 'gradient' && `Degradado de ${theme.gradientColors.length} colores`}
            {theme.backgroundType === 'image' && `Imagen: ${theme.mediaName || 'Personalizada'}`}
            {theme.backgroundType === 'gif' && `GIF Animado: ${theme.mediaName || 'Personalizado'}`}
            {theme.backgroundType === 'video' && `Video: ${theme.mediaName || 'Personalizado'}`}
          </Text>
        </View>

        {/* PESTAÑA 1: COLOR SÓLIDO */}
        {activeTab === 'solid' && (
          <View style={styles.optionsBlock}>
            {/* Paleta Libre / Custom Hex */}
            <View style={[styles.customHexCard, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}>
              <Text style={[styles.customHexTitle, { color: currentColors.textPrimary }]}>
                🎯 Paleta Libre / Color Personalizado (Hex)
              </Text>
              <View style={styles.customHexRow}>
                <TextInput
                  style={[styles.customHexInput, { backgroundColor: currentColors.cardSecondaryBg, borderColor: currentColors.cardBorder, color: currentColors.textPrimary }]}
                  placeholder="#EFE8DE o #181513"
                  placeholderTextColor={currentColors.textMuted}
                  value={customSolidHex}
                  onChangeText={setCustomSolidHex}
                  autoCapitalize="characters"
                  maxLength={7}
                />
                <TouchableOpacity
                  style={[styles.applyHexBtn, { backgroundColor: currentColors.accent }]}
                  onPress={handleApplyCustomSolidHex}
                >
                  <Text style={styles.applyHexBtnText}>Aplicar</Text>
                </TouchableOpacity>
              </View>

              {/* Matriz de muestras de color */}
              <Text style={[styles.swatchesSubtitle, { color: currentColors.textSecondary }]}>
                Toca cualquier color de la muestra para aplicarlo al instante:
              </Text>
              <View style={styles.swatchesGrid}>
                {COLOR_PALETTE_SWATCHES.map((hex) => {
                  const isSelected = theme.backgroundType === 'solid' && theme.solidColor.toUpperCase() === hex.toUpperCase();
                  return (
                    <TouchableOpacity
                      key={hex}
                      style={[
                        styles.swatchCircle,
                        { backgroundColor: hex },
                        isSelected && { borderColor: currentColors.accent, borderWidth: 3 },
                      ]}
                      onPress={() => {
                        setCustomSolidHex(hex);
                        setSolidTheme(hex);
                      }}
                    />
                  );
                })}
              </View>
            </View>

            {/* Temas Predefinidos Completos */}
            <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
              TEMAS PREDEFINIDOS RECOMENDADOS
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

        {/* PESTAÑA 2: DEGRADADOS MULTICOLOR */}
        {activeTab === 'gradient' && (
          <View style={styles.optionsBlock}>
            {/* Editor interactivo de colores del degradado activo */}
            <View style={[styles.gradientEditorCard, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}>
              <Text style={[styles.gradientEditorTitle, { color: currentColors.textPrimary }]}>
                🌈 Colores de este Degradado ({theme.gradientColors.length} colores)
              </Text>
              <Text style={[styles.gradientEditorDesc, { color: currentColors.textSecondary }]}>
                Mínimo 2 colores. Puedes agregar más colores para crear transiciones únicas:
              </Text>

              {/* Lista de Stops */}
              <View style={styles.stopsList}>
                {theme.gradientColors.map((col, idx) => (
                  <View key={idx} style={[styles.stopRow, { borderColor: currentColors.cardBorder }]}>
                    <TouchableOpacity
                      style={[styles.stopColorBtn, { backgroundColor: col }]}
                      onPress={() => setSelectedGradientStopIndex(selectedGradientStopIndex === idx ? null : idx)}
                    />
                    <Text style={[styles.stopHexText, { color: currentColors.textPrimary }]}>
                      Punto #{idx + 1}: <Text style={{ fontWeight: '700' }}>{col}</Text>
                    </Text>

                    {theme.gradientColors.length > 2 && (
                      <TouchableOpacity
                        style={styles.removeStopBtn}
                        onPress={() => removeGradientColor(idx)}
                      >
                        <Text style={styles.removeStopBtnText}>✕ Eliminar</Text>
                      </TouchableOpacity>
                    )}
                  </View>
                ))}
              </View>

              {/* Botón para añadir un nuevo color al degradado */}
              <TouchableOpacity
                style={[styles.addStopBtn, { backgroundColor: currentColors.accent }]}
                onPress={() => {
                  const sampleNewColors = ['#FCE7C3', '#C4D8BC', '#E7D8F2', '#38BDF8', '#F5BCAC'];
                  const pick = sampleNewColors[theme.gradientColors.length % sampleNewColors.length];
                  addGradientColor(pick);
                }}
              >
                <Text style={styles.addStopBtnText}>+ Añadir Color al Degradado</Text>
              </TouchableOpacity>

              {/* Si hay un stop seleccionado, mostrar muestras para cambiarlo */}
              {selectedGradientStopIndex !== null && (
                <View style={[styles.editStopBox, { backgroundColor: currentColors.cardSecondaryBg }]}>
                  <Text style={[styles.editStopTitle, { color: currentColors.textPrimary }]}>
                    Selecciona nuevo color para Punto #{selectedGradientStopIndex + 1}:
                  </Text>
                  <View style={styles.swatchesGrid}>
                    {COLOR_PALETTE_SWATCHES.map((sw) => (
                      <TouchableOpacity
                        key={sw}
                        style={[styles.swatchCircleSmall, { backgroundColor: sw }]}
                        onPress={() => {
                          updateGradientColor(selectedGradientStopIndex, sw);
                          setSelectedGradientStopIndex(null);
                        }}
                      />
                    ))}
                  </View>
                </View>
              )}
            </View>

            {/* Presets de degradados */}
            <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
              ESTILOS DE DEGRADADOS POPULARES
            </Text>
            {PRESET_GRADIENTS.map((g) => {
              const isSelected =
                theme.backgroundType === 'gradient' &&
                theme.gradientColors.join(',') === g.colors.join(',');
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
                    {g.colors.map((c, i) => (
                      <View key={i} style={{ flex: 1, backgroundColor: c }} />
                    ))}
                  </View>
                  <View style={styles.optionRowTextCol}>
                    <Text style={[styles.optionRowTitle, { color: currentColors.textPrimary }]}>
                      {g.name}
                    </Text>
                    <Text style={[styles.optionRowSubtitle, { color: currentColors.textSecondary }]}>
                      {g.colors.length} tonos • {g.isDark ? 'Nocturno' : 'Cálido y suave'}
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

        {/* PESTAÑA 3: IMAGEN DE FONDO */}
        {activeTab === 'image' && (
          <View style={styles.optionsBlock}>
            <TouchableOpacity
              style={[styles.uploadMediaCard, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}
              onPress={() => handlePickLocalMedia('image')}
              disabled={isPickingMedia}
            >
              <Text style={styles.uploadMediaIcon}>🖼️</Text>
              <Text style={[styles.uploadMediaTitle, { color: currentColors.textPrimary }]}>
                {isPickingMedia ? 'Cargando imagen...' : 'Elegir Imagen de tu Teléfono'}
              </Text>
              <Text style={[styles.uploadMediaSubtitle, { color: currentColors.textSecondary }]}>
                Selecciona cualquier foto en alta resolución de tu galería
              </Text>
            </TouchableOpacity>

            {/* Selector de Opacidad del Velo Protector */}
            <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
              INTENSIDAD DEL VELO PROTECTOR DE LECTURA
            </Text>
            <View style={[styles.opacityRow, { backgroundColor: currentColors.cardSecondaryBg }]}>
              {[
                { label: 'Suave (25%)', value: 0.25 },
                { label: 'Medio (45%)', value: 0.45 },
                { label: 'Oscuro (65%)', value: 0.65 },
                { label: 'Noche (80%)', value: 0.8 },
              ].map((op) => (
                <TouchableOpacity
                  key={op.label}
                  style={[
                    styles.opacityBtn,
                    theme.mediaOverlayOpacity === op.value && [styles.opacityBtnActive, { backgroundColor: currentColors.accent }],
                  ]}
                  onPress={() => setMediaOverlayOpacity(op.value)}
                >
                  <Text
                    style={[
                      styles.opacityBtnText,
                      { color: theme.mediaOverlayOpacity === op.value ? '#FFFFFF' : currentColors.textSecondary },
                    ]}
                  >
                    {op.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Muestras Predefinidas de Imágenes */}
            <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
              FONDOS DE BIBLIOTECA PREDEFINIDOS
            </Text>
            <View style={styles.wallpapersGrid}>
              {PRESET_WALLPAPERS.images.map((w) => {
                const isSelected = theme.backgroundType === 'image' && theme.mediaUri === w.uri;
                return (
                  <TouchableOpacity
                    key={w.id}
                    style={[
                      styles.wallpaperItem,
                      isSelected && { borderColor: currentColors.accent, borderWidth: 3 },
                    ]}
                    onPress={() => setMediaTheme(w.uri, 'image', w.name, theme.mediaOverlayOpacity, w.isDark)}
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

        {/* PESTAÑA 4: GIF ANIMADO */}
        {activeTab === 'gif' && (
          <View style={styles.optionsBlock}>
            <TouchableOpacity
              style={[styles.uploadMediaCard, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}
              onPress={() => handlePickLocalMedia('gif')}
              disabled={isPickingMedia}
            >
              <Text style={styles.uploadMediaIcon}>🎬</Text>
              <Text style={[styles.uploadMediaTitle, { color: currentColors.textPrimary }]}>
                {isPickingMedia ? 'Cargando GIF...' : 'Elegir GIF Animado de tu Teléfono'}
              </Text>
              <Text style={[styles.uploadMediaSubtitle, { color: currentColors.textSecondary }]}>
                Fondos animados con movimiento en bucle continuo
              </Text>
            </TouchableOpacity>

            <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
              GIFS ACOGEDORES RECOMENDADOS
            </Text>
            <View style={styles.wallpapersGrid}>
              {PRESET_WALLPAPERS.gifs.map((w) => {
                const isSelected = theme.backgroundType === 'gif' && theme.mediaUri === w.uri;
                return (
                  <TouchableOpacity
                    key={w.id}
                    style={[
                      styles.wallpaperItem,
                      isSelected && { borderColor: currentColors.accent, borderWidth: 3 },
                    ]}
                    onPress={() => setMediaTheme(w.uri, 'gif', w.name, theme.mediaOverlayOpacity, w.isDark)}
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

        {/* PESTAÑA 5: VIDEO DE FONDO */}
        {activeTab === 'video' && (
          <View style={styles.optionsBlock}>
            <TouchableOpacity
              style={[styles.uploadMediaCard, { backgroundColor: currentColors.cardBg, borderColor: currentColors.cardBorder }]}
              onPress={() => handlePickLocalMedia('video')}
              disabled={isPickingMedia}
            >
              <Text style={styles.uploadMediaIcon}>🎥</Text>
              <Text style={[styles.uploadMediaTitle, { color: currentColors.textPrimary }]}>
                {isPickingMedia ? 'Cargando video...' : 'Elegir Video (MP4) de tu Teléfono'}
              </Text>
              <Text style={[styles.uploadMediaSubtitle, { color: currentColors.textSecondary }]}>
                Reproducción de video continuo en segundo plano silenciado
              </Text>
            </TouchableOpacity>

            <Text style={[styles.sectionTitle, { color: currentColors.textMuted }]}>
              VIDEOS ATMOSFÉRICOS DE LECTURA
            </Text>
            <View style={styles.wallpapersGrid}>
              {PRESET_WALLPAPERS.videos.map((w) => {
                const isSelected = theme.backgroundType === 'video' && theme.mediaUri === w.uri;
                return (
                  <TouchableOpacity
                    key={w.id}
                    style={[
                      styles.wallpaperItem,
                      isSelected && { borderColor: currentColors.accent, borderWidth: 3 },
                    ]}
                    onPress={() => setMediaTheme(w.uri, 'video', w.name, theme.mediaOverlayOpacity, w.isDark)}
                  >
                    <View style={[styles.wallpaperThumb, { backgroundColor: '#1A1412', alignItems: 'center', justifyContent: 'center' }]}>
                      <Text style={{ fontSize: 32 }}>▶️</Text>
                    </View>
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
  modeTabsScroll: {
    marginBottom: 14,
  },
  modeTabs: {
    flexDirection: 'row',
    borderRadius: 12,
    padding: 4,
    gap: 4,
  },
  modeTab: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    alignItems: 'center',
    borderRadius: 8,
  },
  modeTabActive: {},
  modeTabText: {
    fontSize: 12,
    fontWeight: '700',
  },
  contrastCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    marginBottom: 14,
  },
  contrastTextCol: {
    flex: 1,
    marginRight: 10,
  },
  contrastCardTitle: {
    fontSize: 13,
    fontWeight: '700',
    marginBottom: 3,
  },
  contrastCardSubtitle: {
    fontSize: 11,
    lineHeight: 15,
  },
  contrastToggleBtn: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
    borderWidth: 1,
  },
  contrastToggleBtnText: {
    fontSize: 11,
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
  previewLabelBadge: {
    marginTop: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
  },
  previewUnderTitle: {
    fontSize: 12,
    fontWeight: '700',
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
  customHexCard: {
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    marginBottom: 10,
  },
  customHexTitle: {
    fontSize: 13,
    fontWeight: '700',
    marginBottom: 8,
  },
  customHexRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
  },
  customHexInput: {
    flex: 1,
    height: 40,
    borderRadius: 8,
    borderWidth: 1,
    paddingHorizontal: 12,
    fontSize: 13,
    fontWeight: '700',
  },
  applyHexBtn: {
    paddingHorizontal: 16,
    height: 40,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  applyHexBtnText: {
    color: '#FFFFFF',
    fontWeight: '700',
    fontSize: 13,
  },
  swatchesSubtitle: {
    fontSize: 11,
    marginBottom: 8,
  },
  swatchesGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  swatchCircle: {
    width: 32,
    height: 32,
    borderRadius: 16,
    borderWidth: 1.5,
    borderColor: 'rgba(0, 0, 0, 0.15)',
  },
  swatchCircleSmall: {
    width: 26,
    height: 26,
    borderRadius: 13,
    borderWidth: 1,
    borderColor: 'rgba(0, 0, 0, 0.15)',
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
  gradientEditorCard: {
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    marginBottom: 10,
  },
  gradientEditorTitle: {
    fontSize: 13,
    fontWeight: '700',
    marginBottom: 4,
  },
  gradientEditorDesc: {
    fontSize: 11,
    lineHeight: 15,
    marginBottom: 10,
  },
  stopsList: {
    gap: 6,
    marginBottom: 10,
  },
  stopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
    gap: 10,
  },
  stopColorBtn: {
    width: 28,
    height: 28,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(0, 0, 0, 0.2)',
  },
  stopHexText: {
    flex: 1,
    fontSize: 12,
  },
  removeStopBtn: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    backgroundColor: '#FEE2E2',
  },
  removeStopBtnText: {
    fontSize: 10,
    color: '#DC2626',
    fontWeight: '700',
  },
  addStopBtn: {
    paddingVertical: 10,
    borderRadius: 10,
    alignItems: 'center',
  },
  addStopBtnText: {
    color: '#FFFFFF',
    fontWeight: '700',
    fontSize: 12,
  },
  editStopBox: {
    marginTop: 10,
    padding: 10,
    borderRadius: 10,
  },
  editStopTitle: {
    fontSize: 11,
    fontWeight: '700',
    marginBottom: 8,
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
  opacityBtnActive: {},
  opacityBtnText: {
    fontSize: 10,
    fontWeight: '600',
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
