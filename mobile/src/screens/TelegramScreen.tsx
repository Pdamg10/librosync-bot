import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  Linking,
  Alert,
  Share,
  SafeAreaView,
} from 'react-native';
import { TelegramLink, LinkCodeResponse } from '../types';
import { fetchTelegramLinks, generateLinkCode } from '../services/api';
import { useAppTheme } from '../theme/ThemeContext';

interface TelegramScreenProps {
  onOpenDrawer?: () => void;
  activeLinkId?: number | null;
  onSelectActiveLink?: (link: TelegramLink) => void;
}

export const TelegramScreen: React.FC<TelegramScreenProps> = ({
  onOpenDrawer,
  activeLinkId,
  onSelectActiveLink,
}) => {
  const { theme } = useAppTheme();
  const c = theme.colors;

  const [links, setLinks] = useState<TelegramLink[]>([]);
  const [linkCodeData, setLinkCodeData] = useState<LinkCodeResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [generating, setGenerating] = useState<boolean>(false);

  const loadLinks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchTelegramLinks();
      setLinks(data);
    } catch (err: any) {
      console.warn('Error al cargar vínculos de Telegram:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLinks();
  }, [loadLinks]);

  const handleGenerateCode = async () => {
    setGenerating(true);
    try {
      const res = await generateLinkCode();
      setLinkCodeData(res);
    } catch (err: any) {
      Alert.alert('Error', 'No se pudo generar el código: ' + err.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleOpenTelegram = async () => {
    if (!linkCodeData) return;
    try {
      await Linking.openURL(linkCodeData.deep_link);
    } catch {
      Alert.alert('Enlace', `Copia este enlace y ábrelo en Telegram:\n${linkCodeData.deep_link}`);
    }
  };

  const handleShareLink = async () => {
    if (!linkCodeData) return;
    try {
      await Share.share({
        message: `🤖 Vincular grupo a LibroSync / Anaquel con este enlace:\n${linkCodeData.deep_link}\n\nO envía en el grupo:\n/enlazar ${linkCodeData.code}`,
      });
    } catch (err) {
      console.warn('Error compartiendo:', err);
    }
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
              Sincronización Telegram
            </Text>
            <Text style={[styles.headerSubtitle, { color: c.textSecondary }]}>
              Aislamiento Único por Grupo y Comunidad
            </Text>
          </View>
        </View>
      </View>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        {/* Banner de Aislamiento Estricto por Grupo */}
        <View style={[styles.isolationNoticeCard, { backgroundColor: '#FEF3C7', borderColor: '#FDE68A' }]}>
          <View style={styles.isolationHeader}>
            <Text style={styles.isolationIcon}>🔒</Text>
            <Text style={[styles.isolationTitle, { color: '#92400E' }]}>
              Aislamiento Seguro por Comunidad
            </Text>
          </View>
          <Text style={[styles.isolationText, { color: '#78350F' }]}>
            Cada grupo conectado posee su propia estantería digital independiente. Los libros, temas y miembros de un grupo nunca se mezclarán con los de otro.
          </Text>
        </View>

        {/* TARJETA 1: GENERACIÓN DEL CÓDIGO ÚNICO POR CUENTA */}
        <View style={[styles.card, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.cardTitle, { color: c.textPrimary }]}>
            🔑 Código Único de Administrador
          </Text>
          <Text style={[styles.cardDesc, { color: c.textSecondary }]}>
            Genera un código único exclusivo para tu cuenta. Con él autorizas a Griffin a organizar y clasificar libros en tu grupo de Telegram.
          </Text>

          {linkCodeData ? (
            <View style={[styles.codeBox, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
              <Text style={[styles.codeLabel, { color: c.textSecondary }]}>
                CÓDIGO GENERADO PARA TU GRUPO:
              </Text>
              <Text style={[styles.codeValue, { color: c.accent }]}>
                {linkCodeData.code}
              </Text>

              <View style={[styles.commandSnippet, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
                <Text style={[styles.commandSnippetLabel, { color: c.textMuted }]}>
                  Envía en tu grupo de Telegram:
                </Text>
                <Text style={[styles.commandSnippetCode, { color: c.textPrimary }]}>
                  /enlazar {linkCodeData.code}
                </Text>
              </View>

              <View style={styles.btnRow}>
                <TouchableOpacity
                  onPress={handleOpenTelegram}
                  style={[styles.actionBtn, { backgroundColor: c.accent }]}
                >
                  <Text style={styles.actionBtnText}>👉 Abrir Bot en Telegram</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  onPress={handleShareLink}
                  style={[styles.shareBtn, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
                >
                  <Text style={[styles.shareBtnText, { color: c.textPrimary }]}>📤 Compartir</Text>
                </TouchableOpacity>
              </View>

              <Text style={[styles.expiryNote, { color: c.textSecondary }]}>
                ⏱️ Este código expira en 15 minutos por seguridad. Una vez vinculado el grupo, la conexión queda guardada de forma permanente.
              </Text>
            </View>
          ) : (
            <TouchableOpacity
              onPress={handleGenerateCode}
              disabled={generating}
              style={[styles.generateBtn, { backgroundColor: c.accent }]}
            >
              {generating ? (
                <ActivityIndicator color="#FAF7F2" />
              ) : (
                <Text style={styles.generateBtnText}>⚡ Generar Código Único de Enlace</Text>
              )}
            </TouchableOpacity>
          )}
        </View>

        {/* TARJETA 2: GRUPOS VINCULADOS A ESTA CUENTA */}
        <View style={[styles.card, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <View style={styles.cardHeaderRow}>
            <Text style={[styles.cardTitle, { color: c.textPrimary }]}>
              📚 Grupos Vinculados ({links.length})
            </Text>
            <TouchableOpacity onPress={loadLinks} style={styles.refreshLinkBtn}>
              <Text style={[styles.refreshLinkText, { color: c.accent }]}>↻ Actualizar</Text>
            </TouchableOpacity>
          </View>

          {loading ? (
            <ActivityIndicator color={c.accent} style={{ marginVertical: 16 }} />
          ) : links.length === 0 ? (
            <View style={styles.emptyNotice}>
              <Text style={styles.emptyNoticeEmoji}>ℹ️</Text>
              <Text style={[styles.emptyNoticeText, { color: c.textSecondary }]}>
                Aún no has vinculado ningún grupo. Genera tu código arriba y añádelo a tu grupo para comenzar.
              </Text>
            </View>
          ) : (
            links.map((link) => {
              const isActive = activeLinkId ? link.id === activeLinkId : link.id === links[0]?.id;
              return (
                <TouchableOpacity
                  key={link.id}
                  style={[
                    styles.linkItem,
                    { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder },
                    isActive && { borderColor: c.accent, borderWidth: 2 },
                  ]}
                  onPress={() => onSelectActiveLink && onSelectActiveLink(link)}
                >
                  <View style={styles.linkTopRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.chatTitle, { color: c.textPrimary }]} numberOfLines={1}>
                        📖 {link.chat_title}
                      </Text>
                      <Text style={[styles.chatIdText, { color: c.textSecondary }]}>
                        Chat ID: {link.chat_id}
                      </Text>
                    </View>
                    <View
                      style={[
                        styles.badge,
                        link.bot_is_admin ? styles.badgeAdmin : styles.badgeNotAdmin,
                      ]}
                    >
                      <Text style={styles.badgeText}>
                        {link.bot_is_admin ? '🛡️ Bot Admin' : 'Miembro'}
                      </Text>
                    </View>
                  </View>

                  <View style={styles.linkFeaturesRow}>
                    <Text style={[styles.featureText, { color: c.textSecondary }]}>
                      {link.forum_enabled ? '✅ Temas (Topics) Activo' : 'ℹ️ Chat sin temas'}
                    </Text>
                    {isActive ? (
                      <View style={[styles.activePill, { backgroundColor: c.accent }]}>
                        <Text style={styles.activePillText}>Biblioteca Activa</Text>
                      </View>
                    ) : (
                      <Text style={[styles.selectPromptText, { color: c.accent }]}>
                        Tocar para explorar →
                      </Text>
                    )}
                  </View>
                </TouchableOpacity>
              );
            })
          )}
        </View>

        {/* TARJETA 3: GUÍA DE CONFIGURACIÓN PASO A PASO */}
        <View style={[styles.card, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <Text style={[styles.cardTitle, { color: c.textPrimary }]}>
            📖 Guía para el Administrador del Grupo
          </Text>

          <View style={styles.stepRow}>
            <View style={[styles.stepNumber, { backgroundColor: c.cardSecondaryBg }]}>
              <Text style={[styles.stepNumberText, { color: c.textPrimary }]}>1</Text>
            </View>
            <Text style={[styles.stepDesc, { color: c.textSecondary }]}>
              Crea tu grupo en Telegram y activa la opción <Text style={{ fontWeight: '700', color: c.textPrimary }}>"Temas (Topics)"</Text> en ajustes.
            </Text>
          </View>

          <View style={styles.stepRow}>
            <View style={[styles.stepNumber, { backgroundColor: c.cardSecondaryBg }]}>
              <Text style={[styles.stepNumberText, { color: c.textPrimary }]}>2</Text>
            </View>
            <Text style={[styles.stepDesc, { color: c.textSecondary }]}>
              Añade a <Text style={{ fontWeight: '700', color: c.textPrimary }}>@LibroSyncBot</Text> como administrador con el permiso de <Text style={{ fontWeight: '700', color: c.textPrimary }}>"Administrar temas"</Text>.
            </Text>
          </View>

          <View style={styles.stepRow}>
            <View style={[styles.stepNumber, { backgroundColor: c.cardSecondaryBg }]}>
              <Text style={[styles.stepNumberText, { color: c.textPrimary }]}>3</Text>
            </View>
            <Text style={[styles.stepDesc, { color: c.textSecondary }]}>
              Genera tu código en esta pantalla y envía <Text style={{ fontWeight: '700', color: c.accent }}>/enlazar &lt;codigo&gt;</Text> en el grupo. ¡Listo!
            </Text>
          </View>
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
  scroll: {
    flex: 1,
  },
  content: {
    padding: 16,
    paddingBottom: 40,
    gap: 14,
  },
  isolationNoticeCard: {
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
  },
  isolationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  isolationIcon: {
    fontSize: 18,
  },
  isolationTitle: {
    fontSize: 13,
    fontWeight: '700',
  },
  isolationText: {
    fontSize: 11,
    lineHeight: 16,
  },
  card: {
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    shadowColor: '#2C221E',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  cardHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  cardTitle: {
    fontSize: 15,
    fontWeight: '700',
    marginBottom: 6,
  },
  cardDesc: {
    fontSize: 12,
    lineHeight: 18,
    marginBottom: 14,
  },
  refreshLinkBtn: {
    padding: 4,
  },
  refreshLinkText: {
    fontSize: 12,
    fontWeight: '700',
  },
  generateBtn: {
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
  },
  generateBtnText: {
    color: '#FAF7F2',
    fontSize: 13,
    fontWeight: '700',
  },
  codeBox: {
    borderRadius: 12,
    padding: 14,
    borderWidth: 1,
    alignItems: 'center',
  },
  codeLabel: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.8,
    marginBottom: 6,
  },
  codeValue: {
    fontSize: 22,
    fontWeight: '800',
    letterSpacing: 1.5,
    marginBottom: 10,
  },
  commandSnippet: {
    width: '100%',
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 12,
  },
  commandSnippetLabel: {
    fontSize: 10,
    fontWeight: '600',
    marginBottom: 2,
  },
  commandSnippetCode: {
    fontSize: 13,
    fontWeight: '800',
    fontFamily: 'monospace',
  },
  btnRow: {
    flexDirection: 'row',
    gap: 8,
    width: '100%',
    marginBottom: 10,
  },
  actionBtn: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 10,
    alignItems: 'center',
  },
  actionBtnText: {
    color: '#FAF7F2',
    fontSize: 12,
    fontWeight: '700',
  },
  shareBtn: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
  },
  shareBtnText: {
    fontSize: 12,
    fontWeight: '700',
  },
  expiryNote: {
    fontSize: 10,
    textAlign: 'center',
    lineHeight: 14,
  },
  emptyNotice: {
    alignItems: 'center',
    paddingVertical: 20,
  },
  emptyNoticeEmoji: {
    fontSize: 28,
    marginBottom: 6,
  },
  emptyNoticeText: {
    fontSize: 12,
    textAlign: 'center',
    lineHeight: 16,
  },
  linkItem: {
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    marginBottom: 10,
  },
  linkTopRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  chatTitle: {
    fontSize: 14,
    fontWeight: '700',
    marginBottom: 2,
  },
  chatIdText: {
    fontSize: 11,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    marginLeft: 8,
  },
  badgeAdmin: {
    backgroundColor: '#D1FAE5',
  },
  badgeNotAdmin: {
    backgroundColor: '#FEE2E2',
  },
  badgeText: {
    fontSize: 10,
    fontWeight: '700',
    color: '#065F46',
  },
  linkFeaturesRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 4,
  },
  featureText: {
    fontSize: 11,
  },
  activePill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  activePillText: {
    color: '#FAF7F2',
    fontSize: 10,
    fontWeight: '700',
  },
  selectPromptText: {
    fontSize: 11,
    fontWeight: '700',
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginBottom: 12,
  },
  stepNumber: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepNumberText: {
    fontSize: 13,
    fontWeight: '800',
  },
  stepDesc: {
    flex: 1,
    fontSize: 12,
    lineHeight: 18,
  },
});
