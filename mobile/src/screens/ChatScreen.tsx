import React, { useState, useRef, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  FlatList,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  SafeAreaView,
  ActivityIndicator,
} from 'react-native';
import { Book, ShelfSummary } from '../types';
import { useAppTheme } from '../theme/ThemeContext';
import { askGriffinAi, getCurrentUserId, updateReadingProgress } from '../services/api';
import { ReaderModal } from '../components/ReaderModal';

interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
  recommendedBooks?: Book[];
}

interface ChatScreenProps {
  onOpenDrawer?: () => void;
  shelves?: ShelfSummary | null;
  catalogBooks?: Book[];
  onSelectBook?: (book: Book) => void;
}

export function ChatScreen({
  onOpenDrawer,
  shelves,
  catalogBooks = [],
  onSelectBook,
}: ChatScreenProps) {
  const { theme } = useAppTheme();
  const c = theme.colors;

  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState<boolean>(false);
  const [selectedBookForReader, setSelectedBookForReader] = useState<Book | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'm-1',
      sender: 'assistant',
      text: '🦉 ¡Hola! Soy Griffin, tu bibliotecario inteligente. ¿Qué te gustaría leer hoy o en qué puedo orientarte sobre tu biblioteca?',
      timestamp: 'Ahora',
      recommendedBooks: catalogBooks.slice(0, 3),
    },
  ]);

  const flatListRef = useRef<FlatList>(null);

  useEffect(() => {
    if (
      catalogBooks.length > 0 &&
      messages.length === 1 &&
      (!messages[0].recommendedBooks || messages[0].recommendedBooks.length === 0)
    ) {
      setMessages([
        {
          id: 'm-1',
          sender: 'assistant',
          text: '🦉 ¡Hola! Soy Griffin, tu bibliotecario inteligente. ¿Qué te gustaría leer hoy o en qué puedo orientarte sobre tu biblioteca?',
          timestamp: 'Ahora',
          recommendedBooks: catalogBooks.slice(0, 3),
        },
      ]);
    }
  }, [catalogBooks]);

  const handleSend = async (textToSend?: string) => {
    const query = (textToSend || inputText).trim();
    if (!query || isTyping) return;

    const userMsg: ChatMessage = {
      id: String(Date.now()),
      sender: 'user',
      text: query,
      timestamp: 'Ahora',
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputText('');
    setIsTyping(true);

    try {
      const response = await askGriffinAi(query, getCurrentUserId());
      const cleanReply = (response.reply || '')
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<b>(.*?)<\/b>/gi, '$1')
        .replace(/<i>(.*?)<\/i>/gi, '$1');

      const assistantMsg: ChatMessage = {
        id: String(Date.now() + 1),
        sender: 'assistant',
        text: cleanReply,
        timestamp: 'Ahora',
        recommendedBooks:
          response.recommended_books && response.recommended_books.length > 0
            ? response.recommended_books
            : undefined,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      // Mensaje de fallback si no hay respuesta de red
      const assistantMsg: ChatMessage = {
        id: String(Date.now() + 1),
        sender: 'assistant',
        text: '📖 No he podido conectar con el servicio de IA en este momento. Revisa tu conexión de red o verifica los ajustes de la biblioteca.',
        timestamp: 'Ahora',
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } finally {
      setIsTyping(false);
    }
  };

  const renderItem = ({ item }: { item: ChatMessage }) => {
    const isUser = item.sender === 'user';

    return (
      <View style={[styles.messageRow, isUser ? styles.messageRowUser : styles.messageRowAssistant]}>
        {!isUser && (
          <View style={[styles.assistantAvatar, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
            <Text style={styles.assistantAvatarText}>🦉</Text>
          </View>
        )}

        <View
          style={[
            styles.bubble,
            isUser
              ? [styles.bubbleUser, { backgroundColor: c.accent }]
              : [styles.bubbleAssistant, { backgroundColor: c.cardBg, borderColor: c.cardBorder }],
          ]}
        >
          <Text
            style={[
              styles.bubbleText,
              isUser ? styles.bubbleTextUser : [styles.bubbleTextAssistant, { color: c.textPrimary }],
            ]}
          >
            {item.text}
          </Text>

          {/* Tarjetas de libros recomendados por Griffin */}
          {item.recommendedBooks && item.recommendedBooks.length > 0 && (
            <View style={styles.recBooksContainer}>
              {item.recommendedBooks.map((book) => (
                <TouchableOpacity
                  key={book.id}
                  style={[styles.recBookMiniCard, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}
                  onPress={() => {
                    if (onSelectBook) onSelectBook(book);
                    else setSelectedBookForReader(book);
                  }}
                >
                  <View style={[styles.recBookSpineHighlight, { backgroundColor: c.accent }]} />
                  <Text style={[styles.recBookTitle, { color: c.textPrimary }]} numberOfLines={1}>
                    {book.title}
                  </Text>
                  <Text style={[styles.recBookAuthor, { color: c.textSecondary }]} numberOfLines={1}>
                    {book.author || 'Autor'} • {book.genre}
                  </Text>
                  <View style={styles.recBookActionRow}>
                    <Text style={[styles.recBookActionText, { color: c.accent }]}>📖 Abrir libro →</Text>
                  </View>
                </TouchableOpacity>
              ))}
            </View>
          )}

          <Text
            style={[
              styles.bubbleTimestamp,
              isUser ? styles.timestampUser : [styles.timestampAssistant, { color: c.textMuted }],
            ]}
          >
            {item.timestamp}
          </Text>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: 'transparent' }]}>
      {/* Header del Chat */}
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
            <Text style={[styles.headerTitle, { color: c.textPrimary }]}>Griffin IA</Text>
            <Text style={styles.headerSubtitle}>Bibliotecario Inteligente • En línea</Text>
          </View>
        </View>
        <View style={styles.headerStatusDot} />
      </View>

      {/* Banner de Asistencia Inmediata */}
      <View style={[styles.supportBanner, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
        <View style={styles.supportBannerTextCol}>
          <Text style={[styles.supportBannerTitle, { color: c.textPrimary }]}>Asistencia en Tiempo Real</Text>
          <Text style={[styles.supportBannerSubtitle, { color: c.textSecondary }]}>
            Conectado con Gemini y la base de datos de tu biblioteca
          </Text>
        </View>
        <View style={[styles.supportBannerArrowCircle, { backgroundColor: c.cardSecondaryBg }]}>
          <Text style={[styles.supportBannerArrow, { color: c.textSecondary }]}>✨</Text>
        </View>
      </View>

      {/* Sugerencias Rápidas Dinámicas */}
      <View style={styles.quickPromptsRow}>
        <TouchableOpacity
          style={[styles.promptPill, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
          onPress={() => handleSend('¿Cuál es mi progreso de lectura actual?')}
          disabled={isTyping}
        >
          <Text style={[styles.promptPillText, { color: c.textPrimary }]}>📊 Mi progreso</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.promptPill, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
          onPress={() => handleSend('Recomiéndame una buena lectura de la biblioteca')}
          disabled={isTyping}
        >
          <Text style={[styles.promptPillText, { color: c.textPrimary }]}>✨ Recomiéndame</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.promptPill, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
          onPress={() => handleSend('¿Cuáles son las últimas novedades de la biblioteca?')}
          disabled={isTyping}
        >
          <Text style={[styles.promptPillText, { color: c.textPrimary }]}>🆕 Ver novedades</Text>
        </TouchableOpacity>
      </View>

      {/* Lista de Mensajes */}
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <FlatList
          ref={flatListRef}
          data={messages}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          contentContainerStyle={styles.messagesList}
          onContentSizeChange={() => flatListRef.current?.scrollToEnd({ animated: true })}
          ListFooterComponent={
            isTyping ? (
              <View style={styles.typingIndicatorRow}>
                <View style={[styles.assistantAvatar, { backgroundColor: c.cardSecondaryBg, borderColor: c.cardBorder }]}>
                  <Text style={styles.assistantAvatarText}>🦉</Text>
                </View>
                <View style={[styles.typingBubble, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
                  <ActivityIndicator size="small" color={c.accent} style={{ marginRight: 8 }} />
                  <Text style={[styles.typingText, { color: c.textSecondary }]}>
                    Griffin está consultando los estantes...
                  </Text>
                </View>
              </View>
            ) : null
          }
        />

        {/* Barra de Entrada Inferior */}
        <View style={[styles.inputContainer, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <TextInput
            style={[styles.input, { backgroundColor: c.cardSecondaryBg, color: c.textPrimary, borderColor: c.cardBorder }]}
            placeholder="Pregúntale a Griffin sobre libros o progreso..."
            placeholderTextColor={c.textMuted}
            value={inputText}
            onChangeText={setInputText}
            onSubmitEditing={() => handleSend()}
            returnKeyType="send"
            editable={!isTyping}
          />

          <TouchableOpacity
            style={[
              styles.sendBtn,
              { backgroundColor: c.accent },
              (!inputText.trim() || isTyping) && styles.sendBtnDisabled,
            ]}
            onPress={() => handleSend()}
            disabled={!inputText.trim() || isTyping}
          >
            {isTyping ? (
              <ActivityIndicator size="small" color="#FFFFFF" />
            ) : (
              <Text style={styles.sendBtnIcon}>➤</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>

      {/* Lector Integrado al tocar una recomendación */}
      <ReaderModal
        visible={selectedBookForReader !== null}
        book={selectedBookForReader}
        onClose={() => setSelectedBookForReader(null)}
        onProgressUpdated={(bookId, progress) => {
          updateReadingProgress(bookId, progress).catch(() => {});
        }}
      />
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
    color: '#10B981',
    fontWeight: '600',
  },
  headerStatusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#10B981',
  },
  supportBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginHorizontal: 16,
    marginTop: 12,
    marginBottom: 8,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
  },
  supportBannerTextCol: {
    flex: 1,
  },
  supportBannerTitle: {
    fontSize: 13,
    fontWeight: '700',
  },
  supportBannerSubtitle: {
    fontSize: 11,
    marginTop: 2,
  },
  supportBannerArrowCircle: {
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 8,
  },
  supportBannerArrow: {
    fontSize: 15,
  },
  quickPromptsRow: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    paddingBottom: 8,
    gap: 8,
  },
  promptPill: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 16,
    borderWidth: 1,
  },
  promptPillText: {
    fontSize: 12,
    fontWeight: '700',
  },
  messagesList: {
    paddingHorizontal: 16,
    paddingBottom: 16,
    paddingTop: 8,
  },
  messageRow: {
    flexDirection: 'row',
    marginBottom: 14,
    alignItems: 'flex-end',
  },
  messageRowUser: {
    justifyContent: 'flex-end',
  },
  messageRowAssistant: {
    justifyContent: 'flex-start',
  },
  assistantAvatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
    marginBottom: 4,
  },
  assistantAvatarText: {
    fontSize: 16,
  },
  bubble: {
    maxWidth: '82%',
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 18,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 3,
    elevation: 1,
  },
  bubbleUser: {
    borderBottomRightRadius: 4,
  },
  bubbleAssistant: {
    borderWidth: 1,
    borderBottomLeftRadius: 4,
  },
  bubbleText: {
    fontSize: 14,
    lineHeight: 21,
  },
  bubbleTextUser: {
    color: '#FFFFFF',
    fontWeight: '500',
  },
  bubbleTextAssistant: {},
  bubbleTimestamp: {
    fontSize: 10,
    marginTop: 5,
    alignSelf: 'flex-end',
  },
  timestampUser: {
    color: 'rgba(255, 255, 255, 0.75)',
  },
  timestampAssistant: {},
  typingIndicatorRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 4,
    marginBottom: 8,
  },
  typingBubble: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 16,
    borderWidth: 1,
  },
  typingText: {
    fontSize: 12,
    fontStyle: 'italic',
  },
  recBooksContainer: {
    marginTop: 10,
    gap: 6,
  },
  recBookMiniCard: {
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
    position: 'relative',
    overflow: 'hidden',
  },
  recBookSpineHighlight: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 4,
  },
  recBookTitle: {
    fontSize: 12,
    fontWeight: '700',
    marginLeft: 4,
  },
  recBookAuthor: {
    fontSize: 11,
    marginLeft: 4,
    marginBottom: 4,
  },
  recBookActionRow: {
    marginLeft: 4,
  },
  recBookActionText: {
    fontSize: 10,
    fontWeight: '700',
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderTopWidth: 1,
    gap: 8,
  },
  input: {
    flex: 1,
    height: 42,
    borderRadius: 21,
    paddingHorizontal: 16,
    fontSize: 14,
    borderWidth: 1,
  },
  sendBtn: {
    width: 42,
    height: 42,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtnDisabled: {
    opacity: 0.45,
  },
  sendBtnIcon: {
    fontSize: 16,
    color: '#FFFFFF',
    fontWeight: '700',
    transform: [{ rotate: '45deg' }],
  },
});
