import { TrendingDown, TrendingUp } from "lucide-react"
import { Badge } from "@/components/UI/Badge"
import {
  Card,
  CardAction,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/UI/Card"

interface SectionCardProps {
  title: string
  description: string
  value: string | number
  trend?: {
    value: number
    isPositive: boolean
  }
  footer?: {
    text: string
    subtext?: string
  }
}

const SectionCard = ({ description, value, trend, footer }: SectionCardProps) => {
  return (
    <Card className="@container/card">
      <CardHeader>
        <CardDescription>{description}</CardDescription>
        <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
          {value}
        </CardTitle>
        {trend && (
          <CardAction>
            <Badge variant="outline">
              {trend.isPositive ? (
                <TrendingUp className="w-3 h-3" />
              ) : (
                <TrendingDown className="w-3 h-3" />
              )}
              {trend.isPositive ? '+' : ''}{trend.value}%
            </Badge>
          </CardAction>
        )}
      </CardHeader>
      {footer && (
        <CardFooter className="flex-col items-start gap-1.5 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium">
            {footer.text}
            {trend?.isPositive ? (
              <TrendingUp className="size-4" />
            ) : (
              <TrendingDown className="size-4" />
            )}
          </div>
          {footer.subtext && (
            <div className="text-muted-foreground">{footer.subtext}</div>
          )}
        </CardFooter>
      )}
    </Card>
  )
}

export const SectionCards = () => {
  return (
    <div className="*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 px-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs lg:px-6 @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
      <SectionCard
        title="Total Cases"
        description="Всего дел"
        value="1,234"
        trend={{ value: 12.5, isPositive: true }}
        footer={{
          text: "Рост за месяц",
          subtext: "Дела за последние 6 месяцев"
        }}
      />
      <SectionCard
        title="Active Cases"
        description="Активные дела"
        value="456"
        trend={{ value: 8.2, isPositive: true }}
        footer={{
          text: "Стабильный рост",
          subtext: "Высокая активность"
        }}
      />
      <SectionCard
        title="Documents"
        description="Документов"
        value="12,345"
        trend={{ value: 15.3, isPositive: true }}
        footer={{
          text: "Увеличение объема",
          subtext: "Обработка документов"
        }}
      />
      <SectionCard
        title="Analysis"
        description="Анализов выполнено"
        value="8,901"
        trend={{ value: 5.7, isPositive: true }}
        footer={{
          text: "Стабильная работа",
          subtext: "Все анализы завершены"
        }}
      />
    </div>
  )
}

