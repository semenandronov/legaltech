"use client"

import * as React from "react"
import {
  Home,
  Settings,
  Search,
  HelpCircle,
  Database,
  FileText,
  BarChart3,
  type LucideIcon,
} from "lucide-react"

import { NavDocuments } from "./NavDocuments"
import { NavMain } from "./NavMain"
import { NavSecondary } from "./NavSecondary"
import { NavUser } from "./NavUser"
import { SearchForm } from "./SearchForm"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/UI/sidebar"

const data = {
  navMain: [
    {
      title: "Дела",
      url: "/cases",
      icon: Home,
    },
    {
      title: "Аналитика",
      url: "/cases",
      icon: BarChart3,
    },
    {
      title: "Настройки",
      url: "/settings",
      icon: Settings,
    },
  ],
  navDocuments: [
    {
      name: "Библиотека данных",
      url: "#",
      icon: Database,
    },
    {
      name: "Отчеты",
      url: "#",
      icon: FileText,
    },
  ],
  navSecondary: [
    {
      title: "Настройки",
      url: "/settings",
      icon: Settings,
    },
    {
      title: "Помощь",
      url: "#",
      icon: HelpCircle,
    },
    {
      title: "Поиск",
      url: "#",
      icon: Search,
    },
  ],
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              className="data-[slot=sidebar-menu-button]:!p-1.5"
            >
              <a href="/">
                <span className="text-xl">⚖️</span>
                <span className="text-base font-semibold">Legal AI</span>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <SearchForm />
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={data.navMain} />
        <NavDocuments items={data.navDocuments} />
        <NavSecondary items={data.navSecondary} className="mt-auto" />
      </SidebarContent>
      <SidebarFooter>
        <NavUser />
      </SidebarFooter>
    </Sidebar>
  )
}



