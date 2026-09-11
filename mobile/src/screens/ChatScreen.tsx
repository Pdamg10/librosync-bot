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
  Image,
} from 'react-native';
import { Book, ShelfSummary } from '../types';
import { useAppTheme } from '../theme/ThemeContext';

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
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'm-1',
      sender: 'assistant',
      text: '👋 ¡Hola! Soy Griffin, tu bibliotecario inteligente. ¿Qué te gustaría leer hoy o en qué puedo orientarte sobre tu biblioteca?',
      timestamp: 'Ahora',
      recommendedBooks: catalogBooks.slice(0, 3),
    },
  ]);

  const flatListRef = useRef<FlatList>(null);

  useEffect(() => {
    // Si la lista de libros cambia y es el mensaje inicial, actualizamos las recomendaciones
    if (catalogBooks.length > 0 && messages.length === 1 && (!messages[0].recommendedBooks || messages[0].recommendedBooks.length === 0)) {
      setMessages([
        {
          id: 'm-1',
          sender: 'assistant',
          text: '👋 ¡Hola! Soy Griffin, tu bibliotecario inteligente. ¿Qué te gustaría leer hoy o en qué puedo orientarte sobre tu biblioteca?',
          timestamp: 'Ahora',
          recommendedBooks: catalogBooks.slice(0, 3),
        },
      ]);
    }
  }, [catalogBooks]);

  const handleSend = (textToSend?: string) => {
    const query = (textToSend || inputText).trim();
    if (!query) return;

    const userMsg: ChatMessage = {
      id: String(Date.now()),
      sender: 'user',
      text: query,
      timestamp: 'Ahora',
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputText('');

    // Respuesta inteligente de Griffin
    setTimeout(() => {
      generateGriffinReply(query);
    }, 600);
  };

  const generateGriffinReply = (query: string) => {
    const q = query.toLowerCase();
    let replyText = '';
    let recs: Book[] = [];

    if (q.includes('progreso') || q.includes('leyendo') || q.includes('avance')) {
      const reading = shelves?.reading || [];
      if (reading.length === 0) {
        replyText = 'Actualmente no tienes libros en curso. ¡Explora el catálogo general o marca uno para comenzar!';
      } else {
        const details = reading
          .map((r) => `• "${r.book?.title}": ${Math.round(r.progress_percent)}% completado`)
          .join('\n');
        replyText = `📊 Este es tu estado de lectura actual:\n\n${details}\n\n¿Quieres continuar la lectura de alguno de ellos?`;
        recs = reading.map((r) => r.book!).filter(Boolean);
      }
    } else if (q.includes('recomiend') || q.includes('popular') || q.includes('suger')) {
      replyText = 'Aquí tienes algunas de las lecturas más populares y comentadas en nuestro club:';
      recs = catalogBooks.slice(0, 3);
    } else if (q.includes('terminad') || q.includes('completad') || q.includes('leído')) {
      const finished = shelves?.finished || [];
      replyText = `Has completado ${finished.length} libro(s) con éxito. 🏆 ¡Excelente hábito de lectura!`;
    } else if (q.includes('fantasia') || q.includes('fantasía') || q.includes('novela') || q.includes('terror') || q.includes('misterio')) {
      const matched = catalogBooks.filter(
        (b) =>
          b.genre.toLowerCase().includes(q) ||
          b.title.toLowerCase().includes(q)
      );
      if (matched.length > 0) {
        replyText = `He encontrado estas opciones relacionadas en el archivo del club:`;
        recs = matched.slice(0, 3);
      } else {
        replyText = `No encontré coincidencias exactas para ese género, pero aquí tienes otros títulos recomendados:`;
        recs = catalogBooks.slice(0, 2);
      }
    } else {
      replyText = `He tomado nota de tu consulta sobre "${query}". Puedes pedirme recomendaciones de libros, consultar tu progreso o pedir detalles de cualquier autor.`;
      if (catalogBooks.length > 0) {
        recs = [catalogBooks[Math.floor(Math.random() * catalogBooks.length)]];
      }
    }

    const assistantMsg: ChatMessage = {
      id: String(Date.now() + 1),
      sender: 'assistant',
      text: replyText,
      timestamp: 'Ahora',
      recommendedBooks: recs.length > 0 ? recs : undefined,
    };

    setMessages((prev) => [...prev, assistantMsg]);
  };

  const renderItem = ({ item }: { item: ChatMessage }) => {
    const isUser = item.sender === 'user';

    return (
      <View style={[styles.messageRow, isUser ? styles.messageRowUser : styles.messageRowAssistant]}>
        {!isUser && (
          <View style={styles.assistantAvatar}>
            <Text style={styles.assistantAvatarText}>🦉</Text>
          </View>
        )}

        <View style={[styles.bubble, isUser ? styles.bubbleUser : styles.bubbleAssistant]}>
          <Text style={[styles.bubbleText, isUser ? styles.bubbleTextUser : styles.bubbleTextAssistant]}>
            {item.text}
          </Text>

          {/* Tarjetas de libros recomendados dentro del mensaje (como en la imagen de referencia) */}
          {item.recommendedBooks && item.recommendedBooks.length > 0 && (
            <View style={styles.recBooksContainer}>
              {item.recommendedBooks.map((book) => (
                <TouchableOpacity
                  key={book.id}
                  style={styles.recBookMiniCard}
                  onPress={() => onSelectBook && onSelectBook(book)}
                >
                  <View style={styles.recBookSpineHighlight} />
                  <Text style={styles.recBookTitle} numberOfLines={1}>{book.title}</Text>
                  <Text style={styles.recBookAuthor} numberOfLines={1}>{book.author || 'Autor'}</Text>
                  <View style={styles.recBookActionRow}>
                    <Text style={styles.recBookActionText}>Abrir libro →</Text>
                  </View>
                </TouchableOpacity>
              ))}
            </View>
          )}

          <Text style={[styles.bubbleTimestamp, isUser ? styles.timestampUser : styles.timestampAssistant]}>
            {item.timestamp}
          </Text>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: c.canvasBg }]}>
      {/* Header del Chat */}
      <View style={[styles.header, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
        <View style={styles.headerLeft}>
          {onOpenDrawer && (
            <TouchableOpacity onPress={onOpenDrawer} style={[styles.menuBtn, { backgroundColor: c.cardSecondaryBg }]}>
              <Text style={[styles.menuIcon, { color: c.textPrimary }]}>☰</Text>
            </TouchableOpacity>
          )}
          <View>
            <Text style={[styles.headerTitle, { color: c.textPrimary }]}>Chat con Griffin</Text>
            <Text style={styles.headerSubtitle}>Bibliotecario IA • En línea</Text>
          </View>
        </View>
        <View style={styles.headerStatusDot} />
      </View>

      {/* Banner de Asistencia y Soporte Inmediato (Estilo Imagen de Referencia) */}
      <View style={[styles.supportBanner, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
        <View style={styles.supportBannerTextCol}>
          <Text style={[styles.supportBannerTitle, { color: c.textPrimary }]}>Asistencia del Club</Text>
          <Text style={[styles.supportBannerSubtitle, { color: c.textSecondary }]}>
            Recomendaciones y consultas sobre el catálogo
          </Text>
        </View>
        <View style={[styles.supportBannerArrowCircle, { backgroundColor: c.cardSecondaryBg }]}>
          <Text style={[styles.supportBannerArrow, { color: c.textSecondary }]}>›</Text>
        </View>
      </View>

      {/* Sugerencias Rápidas / Pills */}
      <View style={styles.quickPromptsRow}>
        <TouchableOpacity
          style={[styles.promptPill, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
          onPress={() => handleSend('¿Cuál es mi progreso de lectura?')}
        >
          <Text style={[styles.promptPillText, { color: c.textSecondary }]}>📊 Mi progreso</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.promptPill, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
          onPress={() => handleSend('Recomiéndame un buen libro')}
        >
          <Text style={[styles.promptPillText, { color: c.textSecondary }]}>✨ Recomiéndame</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.promptPill, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}
          onPress={() => handleSend('¿Qué libros hay en la biblioteca?')}
        >
          <Text style={[styles.promptPillText, { color: c.textSecondary }]}>📚 Ver novedades</Text>
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
        />

        {/* Barra de Entrada Inferior (Estilo Imagen de Referencia) */}
        <View style={[styles.inputContainer, { backgroundColor: c.cardBg, borderColor: c.cardBorder }]}>
          <TouchableOpacity
            style={[styles.attachBtn, { backgroundColor: c.cardSecondaryBg }]}
            onPress={() => alert('Adjuntar notas o pasajes favoritos')}
          >
            <Text style={[styles.attachBtnIcon, { color: c.textSecondary }]}>📎</Text>
          </TouchableOpacity>

          <TextInput
            style={[styles.input, { backgroundColor: c.cardSecondaryBg, color: c.textPrimary }]}
            placeholder="Escribe un mensaje a Griffin..."
            placeholderTextColor={c.textMuted}
            value={inputText}
            onChangeText={setInputText}
            onSubmitEditing={() => handleSend()}
            returnKeyType="send"
          />

          <TouchableOpacity
            style={[styles.sendBtn, !inputText.trim() && styles.sendBtnDisabled]}
            onPress={() => handleSend()}
            disabled={!inputText.trim()}
          >
            <Text style={styles.sendBtnIcon}>➤</Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 14,
    backgroundColor: '#FBF8F3',
    borderBottomWidth: 1,
    borderBottomColor: '#DFD5C6',
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
    backgroundColor: '#EDE5D8',
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuIcon: {
    fontSize: 18,
    color: '#2C221E',
  },
  headerTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: '#2C221E',
  },
  headerSubtitle: {
    fontSize: 12,
    color: '#059669',
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
    backgroundColor: '#FBF8F3',
    marginHorizontal: 16,
    marginTop: 12,
    marginBottom: 8,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#DFD5C6',
  },
  supportBannerTextCol: {
    flex: 1,
  },
  supportBannerTitle: {
    fontSize: 13,
    fontWeight: '700',
    color: '#2C221E',
  },
  supportBannerSubtitle: {
    fontSize: 11,
    color: '#7A6E65',
    marginTop: 2,
  },
  supportBannerArrowCircle: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: '#EDE5D8',
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 8,
  },
  supportBannerArrow: {
    fontSize: 14,
    fontWeight: '700',
    color: '#7A6E65',
  },
  quickPromptsRow: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    paddingBottom: 8,
    gap: 8,
  },
  promptPill: {
    backgroundColor: '#FBF8F3',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#DFD5C6',
  },
  promptPillText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#7A6E65',
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
    backgroundColor: '#EDE5D8',
    borderWidth: 1,
    borderColor: '#DFD5C6',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
    marginBottom: 4,
  },
  assistantAvatarText: {
    fontSize: 16,
  },
  bubble: {
    maxWidth: '80%',
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 18,
    shadowColor: '#2C221E',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.04,
    shadowRadius: 3,
    elevation: 1,
  },
  bubbleUser: {
    backgroundColor: '#8E75B2',
    borderBottomRightRadius: 4,
  },
  bubbleAssistant: {
    backgroundColor: '#FBF8F3',
    borderWidth: 1,
    borderColor: '#DFD5C6',
    borderBottomLeftRadius: 4,
  },
  bubbleText: {
    fontSize: 14,
    lineHeight: 20,
  },
  bubbleTextUser: {
    color: '#FFFFFF',
  },
  bubbleTextAssistant: {
    color: '#2C221E',
  },
  bubbleTimestamp: {
    fontSize: 10,
    marginTop: 4,
    alignSelf: 'flex-end',
  },
  timestampUser: {
    color: 'rgba(255, 255, 255, 0.7)',
  },
  timestampAssistant: {
    color: '#9C8E82',
  },
  recBooksContainer: {
    marginTop: 10,
    gap: 6,
  },
  recBookMiniCard: {
    backgroundColor: '#F3EDE2',
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#DFD5C6',
    position: 'relative',
    overflow: 'hidden',
  },
  recBookSpineHighlight: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 4,
    backgroundColor: '#D97706',
  },
  recBookTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: '#2C221E',
    marginLeft: 4,
  },
  recBookAuthor: {
    fontSize: 11,
    color: '#7A6E65',
    marginLeft: 4,
    marginBottom: 4,
  },
  recBookActionRow: {
    marginLeft: 4,
  },
  recBookActionText: {
    fontSize: 10,
    fontWeight: '700',
    color: '#B45309',
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: '#FBF8F3',
    borderTopWidth: 1,
    borderTopColor: '#DFD5C6',
    gap: 8,
  },
  attachBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#EDE5D8',
    alignItems: 'center',
    justifyContent: 'center',
  },
  attachBtnIcon: {
    fontSize: 18,
    color: '#7A6E65',
  },
  input: {
    flex: 1,
    height: 40,
    backgroundColor: '#EDE5D8',
    borderRadius: 20,
    paddingHorizontal: 16,
    fontSize: 14,
    color: '#2C221E',
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#E06D53',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtnDisabled: {
    backgroundColor: '#D5CCC0',
  },
  sendBtnIcon: {
    fontSize: 16,
    color: '#FFFFFF',
    fontWeight: '700',
    transform: [{ rotate: '45deg' }],
  },
});
